mod memory;
mod source;
mod inference;
mod app;
mod terminal;
mod agent;
mod embeddings;
mod appstore;
mod model;
mod config;
mod server;
mod protocol;

use anyhow::Error;
use chrono::Local;
use itertools::Itertools;
use memory::Memory;
use serde_json::Value;

use env_logger;
use std::sync::{Arc};
use inference::{OLLAMA,Gemini,HuggingFace};
use inference::{OllamaConfig,GeminiConfig,HuggingFaceConfig};
use inference::inference_api_trait;
use terminal::Terminal;
use app::{App,AppType};
use protocol::{Protocol,ProtocolStore};
use agent::{Agent,AgentPulse,AgentStore};
use embeddings::{embedder};
use std::collections::{HashMap, HashSet};
use std::thread::sleep;
use tokio::time::{ Duration};
use crate::appstore::AppStore;
use crate::memory::{MemoryNode,MemoryNodeType};
use crate::model::PosModel;
use std::fs;
use crate::server::RuntimeServer;
use pyo3::prelude::*;
use pyo3_asyncio::tokio::future_into_py;
use tokio::sync::RwLock;
use crate::source::Source;
use config::InferenceStore;
use log::{info, warn, error, debug, trace};
use std::fs::OpenOptions;
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt, filter::LevelFilter};
use tracing_subscriber::{ EnvFilter};
use tracing_subscriber::Layer;
pub fn init_tracing() {
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open("kattalai_rust.log")
        .unwrap();

    let level_filter = LevelFilter::INFO;

    let file_layer = fmt::layer()
        .with_writer(file)
        .with_ansi(false)
        .with_filter(level_filter);

    // let console_layer = fmt::layer()
    //     .with_target(false) 
    //     .compact()
    //     .with_filter(level_filter);

    let filter = EnvFilter::new("info,nlprule=error");

    let _ = tracing_subscriber::registry()
        .with(filter)
        .with(file_layer)
        .try_init(); 
}

pub struct Runtime{
    topics:HashMap<String,Arc<Memory>>,
    users:HashMap<String,Source>,
    agents:HashMap<String,Arc<tokio::sync::RwLock<Arc<Agent>>>>,
    embedder:Arc<embedder>,
    app_store:Arc<AppStore>,
    inference_store:Arc<InferenceStore>,
    agent_store:Arc<AgentStore>,
    protocols_store:Arc<ProtocolStore>,
    runtime_card:Source
}

impl Runtime{
    pub async fn new(bind:Option<String>)->Arc<RwLock<Self>>{
        
        println!("Initializing protocol...");
        let embedder=embedder::new("./model_assets/bge-small-en-v1.5".to_string()).await;
        let app_store=AppStore::new("./apps/".to_string(),embedder.clone()).await;
        let inference_store=InferenceStore::load_configs("./configs/inference_config.toml");
        let protocol_store=ProtocolStore::new("./protocols/".to_string(),app_store.clone(),inference_store.clone());
        let agent_store=AgentStore::load_agents("./configs/agents_config.toml", inference_store.clone(), app_store.clone(),protocol_store.clone());

        let sharedruntime= Arc::new(RwLock::new(Self{
            topics:HashMap::new(),
            users:HashMap::new(),
            agents:HashMap::new(),
            embedder,
            app_store,
            inference_store,
            agent_store:Arc::new(agent_store),
            protocols_store:protocol_store,
            runtime_card:Source::new(source::Role::Runtime, "Runtime".to_string(), None)
        }));

        if let Some(addr)=bind{
            RuntimeServer::serve(sharedruntime.clone(), addr).await;
        }


        sharedruntime



    }

    pub async fn get_agents_list(&self)->Vec<String>{
        self.agent_store.list_agents()
    }

    pub async fn create_topic_thread(&mut self)->String{
        let memory = Memory::new(Some(self.protocols_store.clone()));
        let memory_id_clone=memory._memory_id.clone();
        self.topics.insert(memory_id_clone.clone(), memory);
        memory_id_clone
    }
    pub async fn create_user(&mut self,user_name:String)->String{
        let user_node=source::Source::new(source::Role::User, user_name, None  );
        let user_node_id=user_node.get_id();
        self.users.insert(user_node_id.clone(), user_node);
        user_node_id


    }
    pub async fn deploy_agent(&mut self,agent_name:String)->String{
        let agent=self.agent_store.get_agent(agent_name);
        let agent_id=agent.read().await.get_agent_id();
        self.agents.insert(agent_id.clone(), agent.clone());
        agent_id


    }
    pub async fn get_topic_history_len(&self,topic_id:&String)->Result<usize,&str>{
        if self.topics.contains_key(topic_id){
            let mlen=self.topics.get(topic_id).unwrap().get_memory_len().await;
            Ok(mlen)
        }
        else{
            Err("Topic not found")
        }
    } 
    pub async fn get_agent_episode_history_len(&self,topic_id:&String,agent_id:&String)->Result<usize,&str>{
        if self.topics.contains_key(topic_id){
            if self.agents.contains_key(agent_id){
                let cagent=self.agents.get(agent_id).unwrap();
                let mlen=cagent.read().await.get_episode_len(topic_id.clone()).await;
                Ok(mlen)
            }
            else{
                Err("Agent not found")
            }
        }
        else{
            Err("Topic not found")
        }
    }
    pub async fn insert_message(&self,topic_id:&String,user_id:&String,message:String)->Result<&str,&str>{
        if self.topics.contains_key(topic_id){
            if self.users.contains_key(user_id){
            
                let memory = self.topics.get(topic_id).unwrap();
                info!("Memory instance created...");

                memory.insert(memory::MemoryNode::new(
                    &self.users.get(user_id).unwrap(),
                    message,
                    None,
                    memory::MemoryNodeType::Message,
                    None,
                    None,
                )).await;

                Ok("Message Inserted")
            }
            else{
                Err("User not found")
            }

        }
        else{
            Err("Topic Id Not Found.")
        }
    }

    pub async fn add_agent_to_topic(&self,topic_id:&String,agent_id:&String)->Result<&str,&str>{
        if self.topics.contains_key(topic_id){
            if self.agents.contains_key(agent_id){
                let agent=self.agents.get(agent_id).unwrap().clone();
                let topic=self.topics.get(topic_id).unwrap().clone();

                Agent::ping(&agent,AgentPulse::NewEpisode(format!("Interface Episode:{}",topic_id.clone()),Some(topic))).await;

                Ok("Agent added successfully")
            }
            else{
                Err("Agent not found")
            }
        }
        else{
            Err("Topic not found")
        }
    }
    pub async fn iter_topic(&self,topic_id:&String,start_index:usize)->Result<impl Iterator<Item = MemoryNode> ,&str>{
        if self.topics.contains_key(topic_id){
            let topic=self.topics.get(topic_id).unwrap();
            Ok(topic.iter_memory(Some(start_index), None, Some(&self.runtime_card)).await)

        }
        else{
            Err("Topic Id Not Found.")
        }

    }
    pub async fn iter_agent_memory(&self,topic_id:&String,agent_id:&String,start_index:usize)->Result<impl Iterator<Item = MemoryNode> ,String>{
        if self.topics.contains_key(topic_id){
            if self.agents.contains_key(agent_id){
                let topic=self.topics.get(topic_id).unwrap();
                let agent=self.agents.get(agent_id).unwrap().clone();
                let topic_id_clone=topic_id.clone();

                let iter=Agent::iter_episode_memory(agent,topic_id_clone,start_index,None).await;
                iter
            }
            else{
                Err("Agent Not Found.".to_string())
            }

        }
        else{
            Err("Topic Id Not Found.".to_string())
        }

    }
    pub async fn remove_agent_from_topic(&self,topic_id:&String,agent_id:&String)->Result<&str,&str>{
        if self.agents.contains_key(agent_id){
            let agent=self.agents.get(agent_id).unwrap().clone();
            agent.read().await.detach_episode(topic_id.clone()).await;
            Ok("Agent added successfully")
        }
        else{
            Err("Agent not found")
        }
    }
    pub async fn is_agent_working_on_topic(&self,topic_id:&String,agent_id:&String)->Result<bool,&str>{
        if self.topics.contains_key(topic_id){
            if self.agents.contains_key(agent_id){
                let cagent=self.agents.get(agent_id).unwrap();
                Ok(cagent.read().await.get_agent_episode_status(topic_id.clone()).await)
            }
            else{
                Err("Agent not found")
            }
        }
        else{
            Err("Topic not found")
        }
    }
    

}


///PyRuntime
/// 
use futures::executor::block_on;

#[pyclass]
pub struct PyRuntime {
    inner: Arc<RwLock<Runtime>>,
}

#[pymethods]
impl PyRuntime {

    #[staticmethod]
    fn create(py: Python<'_>,bind:Option<String>) -> PyResult<&PyAny> {

        future_into_py(py, async move {

            init_tracing();
            // env_logger::init();
            let rt = block_on(Runtime::new(bind));

            Python::with_gil(|py| {
                Py::new(py, PyRuntime {
                    inner: rt,
                })
            })
        })
    }

    fn create_topic_thread<'py>(&self, py: Python<'py>) -> PyResult<&'py PyAny> {
        let runtime = self.inner.clone();

        future_into_py(py, async move {
            let mut rt = runtime.write().await;
            let topic_id =rt.create_topic_thread().await;
            Ok(topic_id)
        })
    }

    fn create_user<'py>(&self, py: Python<'py>, user_name: String) -> PyResult<&'py PyAny> {
        let runtime = self.inner.clone();

        future_into_py(py, async move {
            let mut rt = runtime.write().await;
            let uid = rt.create_user(user_name).await;           
            
            Ok(uid)
        })
    }

    fn deploy_agent<'py>(&self, py: Python<'py>, agent_name: String) -> PyResult<&'py PyAny> {
        let runtime = self.inner.clone();

        future_into_py(py, async move {
            let mut rt = runtime.write().await;
            let aid = rt.deploy_agent(agent_name).await;
            Ok(aid)
        })
    }

    fn insert_message<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        user_id: String,
        message: String
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        future_into_py(py, async move {

            let readable_rt = rt.read().await;
            let result=readable_rt.insert_message(&topic_id, &user_id, message).await;
            
            match result.clone() {
                Ok(v) => Ok(v.to_string()),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        })
    }

    fn topic_history_len<'py>(
            &self,
            py: Python<'py>,
            topic_id: String
        ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        future_into_py(py, async move {
            let readable_rt = rt.read().await;
            let ln=readable_rt.get_topic_history_len(&topic_id).await;

            match ln.clone() {
                Ok(v) => Ok(v),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        })
    }

    fn agent_episode_len<'py>(
            &self,
            py: Python<'py>,
            topic_id: String,
            agent_id: String
        ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        future_into_py(py, async move {
            let readable_rt = rt.read().await;
            let ln=readable_rt.get_agent_episode_history_len(&topic_id,&agent_id).await;

            match ln.clone() {
                Ok(v) => Ok(v),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        })
    }

    fn add_agent_to_topic<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        agent_id: String
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {

            let runtime = rt.read().await;
            let result=runtime.add_agent_to_topic(&topic_id, &agent_id).await;

            match result {
                Ok(msg) => Ok(msg.to_string()),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }

        })
    }
    fn remove_agent_from_topic<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        agent_id: String
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {

            let runtime = rt.read().await;
            let result=runtime.remove_agent_from_topic(&topic_id, &agent_id).await;

            match result {
                Ok(msg) => Ok(msg.to_string()),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }

        })
    }
    
    fn get_agent_list<'py>(
        &self,
        py: Python<'py>
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {

            let runtime = rt.read().await;
            Ok(runtime.get_agents_list().await)

        })
    }

    fn iter_topic<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        start_index: usize
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {

            let runtime = rt.read().await;
            let result=runtime.iter_topic(&topic_id, start_index).await;

            match result {
                Ok(iter) => {
                    let converted_vec:Vec<Value> = iter.map(|p|{p.get_json()}).collect();
                    let json = serde_json::to_string(&converted_vec).unwrap();
                    Ok(json)
                }
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }

        })
    }

    fn iter_agent_episode<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        agent_id: String,
        start_index: usize
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {

            let runtime = rt.read().await;
            let result=runtime.iter_agent_memory(&topic_id, &agent_id,start_index).await;

            match result {
                Ok(iter) => {
                    let converted_vec:Vec<Value> = iter.map(|p|{p.get_json()}).collect();
                    let json = serde_json::to_string(&converted_vec).unwrap();
                    Ok(json)
                }
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }

        })
    }
    fn is_agent_working_on_topic<'py>(
        &self,
        py: Python<'py>,
        topic_id: String,
        agent_id: String,
    ) -> PyResult<&'py PyAny> {

        let rt = self.inner.clone();

        future_into_py(py, async move {
            let readable_rt = rt.read().await;
            let ln=readable_rt.is_agent_working_on_topic(&topic_id,&agent_id).await;

            match ln.clone() {
                Ok(v) => Ok(v),
                Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        })
    }
}

#[pymodule]
fn soulengine(_py: Python, m: &PyModule) -> PyResult<()> {

    m.add_class::<PyRuntime>()?;

    Ok(())
}