use crate::appstore::AppStore;
use futures::executor::block_on;
use crate::{agent, memory, source};
use crate::memory::{Memory,MemoryNode,MemoryNodeType,IOPhase};
use crate::source::{Source,Role};
use crate::terminal::Terminal;
use crate::inference::{ inference_api_trait,invoke_type};
use crate::embeddings::embedder;
use crate::app::App;
use crate::protocol::{ProtocolStore, ProtocolConfig};
use core::error;

use std::sync::atomic::{AtomicBool, Ordering};
use std::hash::Hash;
use std::mem;
use std::process::Output;
use std::ptr::read;
use std::sync::{Arc};
use tokio::sync::RwLock;
use std::thread::sleep;
use anyhow::Error;
use regex::Regex;
use reqwest::header::AGE;
use std::fmt::{self, format};
use serde::Deserialize;
use std::fs;
use crate::InferenceStore;
use crossbeam::channel;
use chrono::format;
use uuid::Uuid;
use std::{
    clone,
    collections::{HashMap, HashSet},
    thread,
};
use memory::MemoryType;
use sysinfo::System;
use tokio::time::{interval, Duration};

use tokio::sync::Mutex;

use log::{info, warn, error, debug, trace};

use sysinfo::{ Disks};

pub fn get_sys_info() -> String {
    let mut sys = System::new_all();
    // We must refresh the system data to get current values
    sys.refresh_all();

    let os_name = System::name().unwrap_or_else(|| "Unknown".to_string());
    let os_version = System::os_version().unwrap_or_else(|| "Unknown".to_string());
    let kernel = System::kernel_version().unwrap_or_else(|| "Unknown".to_string());
    let host = System::host_name().unwrap_or_else(|| "Unknown".to_string());
    
    // RAM is usually returned in bytes; converting to GB
    let total_ram_gb = sys.total_memory() / 1024 / 1024 / 1024;
    let used_ram_gb = sys.used_memory() / 1024 / 1024 / 1024;

    // CPU info
    let cpu_count = sys.cpus().len();
    let cpu_brand = sys.cpus().get(0)
        .map(|c| c.brand())
        .unwrap_or("Unknown CPU");

    format!(
        "
        Hostname:     {}\n\
        OS:           {} (v{})\n\
        Kernel:       {}\n\
        CPU:          {} ({} Cores)\n\
        RAM:          {}GB / {}GB used\n\
        ---------------------------",
        host, os_name, os_version, kernel, cpu_brand, cpu_count, used_ram_gb, total_ram_gb
    )
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum PromptStyle{
    REASONING,
    RAC,
    TOF,
    PROTOCOL,
    REPAIR
}
pub struct episode{
    episode_id:String,
    episode_memory:Arc<Memory>,
    episode_desc:String,
    interface_memory:Option<Arc<Memory>>,
    last_fetched_imemory_id:Mutex<Option<String>>,
    agent_lock:Mutex<bool>,
    followup_planned:Mutex<bool>,
}
impl  episode {
    pub fn get_episode_id(&self)->String{
        self.episode_id.clone()
    }
    pub fn get_episode_memory_branch_id(&self)->String{
        self.episode_memory.get_branch_id()
    }
    pub fn branch_episode_memory(&self)->Arc<Memory>{
        self.episode_memory.branch()
    }
    pub fn get_read_only_episode_memory(&self)->Arc<Memory>{
        self.episode_memory.get_ready_only_copy()
    }
    pub async fn episode_memory_len(&self)->usize{
        self.episode_memory.get_memory_len().await
    }
    pub async fn get_agent_lock_status(&self)->bool{
        let locked_agent_lock=self.agent_lock.lock().await;
        (*locked_agent_lock).clone()
    }
    pub async fn get_followup_planned_status(&self)->bool{
        let followup_status=self.followup_planned.lock().await;
        (*followup_status).clone()  
    }
    pub async fn is_episode_active(&self)->bool{
        let locked_agent_lock=self.agent_lock.lock().await;
        let followup_status=self.followup_planned.lock().await;

        (*locked_agent_lock).clone() || (*followup_status).clone()
    }
    pub async fn lock_agent(&self){
        let mut locked_agent_lock=self.agent_lock.lock().await;
        *locked_agent_lock=true;

    }
    pub async fn unlock_agent(&self){
        let mut locked_agent_lock=self.agent_lock.lock().await;
        *locked_agent_lock=false;

    }
    pub async fn set_lastfetch_memoryid(&self,lid:String){
        let mut locked_id=self.last_fetched_imemory_id.lock().await;
        *locked_id=Some(lid);

    }
    pub async fn set_followup_planned(&self, followup_planned: bool){
        let mut followup_status=self.followup_planned.lock().await;
        *followup_status=followup_planned;
    }
    
}

#[derive(Debug)]
pub enum AgentPulse{
    Invoke(Option<String>),
    Generate,
    NewEpisode(String,Option<Arc<Memory>>,bool),
    AttachApp(App),
    AddMemory(MemoryNode,Option<String>),
    AddMultipleMemories(Vec<MemoryNode>,Option<String>),
    AddMultipleMemoriesAndInvoke(Vec<MemoryNode>,Option<String>),
    AddMemoryAndInvoke(MemoryNode,Option<String>),
    UpdateEpisode(String,String),
    unlockAgentForEpisode(String),
    lockAgentForEpisode(String),
    SetAgentFollowupStatus(String,bool),
}

#[derive(Debug)]
pub enum EpisodePulse{
    AttachListener(String,Arc<Memory>,Arc<Memory>),
}
fn check_for_invoke_trigger(new_memories:&Vec<MemoryNode>)->bool{
        let triggerable_roles=vec![Role::Agent,Role::User];
        new_memories.iter().any(|mem_node|{

            (mem_node.get_source_role()==Role::User ||
            mem_node.get_node_type()==MemoryNodeType::ProtocolPrompt)&&
            (!mem_node.get_content().trim().starts_with("/"))

        })
}


#[derive(Debug,Deserialize,Clone)]
pub struct agent_model_config{
    pub inference_provider:String,
    pub model_id:String
}

#[derive(Deserialize,Clone)]
pub struct agent_config{
    agent_name:String,
    agent_goal:String,
    backstory:String,
    reasoning_model:Option<agent_model_config>,
    nlp_model:Option<agent_model_config>,
    default_apps:Vec<String>,
    allow_self_selected_apps:bool,
}#[derive(Deserialize,Clone)]
pub struct DefaultModelConfig{
    default_reasoning_model:agent_model_config,
    default_nlp_model:agent_model_config,
}

#[derive(Deserialize,Clone)]
pub struct AgentConfigs{
    agent_config:Vec<agent_config>
}
pub struct AgentStore{
    agents_config:HashMap<String,agent_config>,
    inference_store:Arc<InferenceStore>,
    app_store:Arc<AppStore>,
    protocols_store:Arc<ProtocolStore>

}
impl AgentStore{
    pub fn load_agents(agent_config_path:&str,inference_store:Arc<InferenceStore>,app_store:Arc<AppStore>,protocols_store:Arc<ProtocolStore>)->Self{
        let content = fs::read_to_string(agent_config_path).unwrap();
        let cogitare_toml=include_str!("../prompts/cogitare_config.toml").to_string();
        let default_model_toml=fs::read_to_string("./configs/model_config.toml").unwrap();
        let mut config: AgentConfigs = toml::from_str(&content).unwrap();
        let cogitare_config: AgentConfigs = toml::from_str(&cogitare_toml).unwrap();
        let default_model_config: DefaultModelConfig = toml::from_str(&default_model_toml).unwrap();
        config.agent_config.push(cogitare_config.agent_config[0].clone());

        for agent_conf in config.agent_config.iter_mut(){
            if agent_conf.reasoning_model.is_none(){
                agent_conf.reasoning_model=Some(default_model_config.default_reasoning_model.clone());
            }
            if agent_conf.nlp_model.is_none(){
                agent_conf.nlp_model=Some(default_model_config.default_nlp_model.clone());
            }

            if agent_conf.reasoning_model.is_none() || agent_conf.nlp_model.is_none(){
                panic!("Agent:{} does not have valid model configuration",agent_conf.agent_name);
            }
        }
        
        let mut agent_map=HashMap::new();

        let std_apps=vec![
            "protocoladmin".to_string(),
            "appfinder".to_string(),
            "codex_app".to_string(),
        ];
        for mut agent in config.agent_config{
            for std_app in std_apps.clone(){
                if !agent.default_apps.contains(&std_app){
                    info!("Adding default app:{} to agent:{}",std_app,agent.agent_name);
                    agent.default_apps.push(std_app.clone());

                }
            }
            agent_map.insert(agent.agent_name.clone(), agent.clone());
        }

        Self{
            agents_config:agent_map,
            inference_store,
            app_store,
            protocols_store
        }

    }
    pub fn list_agents(&self)->Vec<String>{
        let mut agents = self.agents_config.keys().cloned().collect::<Vec<String>>();
        agents.sort();
        agents
    }
    pub fn get_agent(&self,agent_name:String)->Arc<RwLock<Arc<Agent>>>{

        if self.agents_config.contains_key(&agent_name){

            let aconfig=self.agents_config.get(&agent_name).unwrap();

            

            let reasoning_model=self.inference_store.get_model(aconfig.reasoning_model.as_ref().unwrap().inference_provider.clone(),&aconfig.reasoning_model.as_ref().unwrap().model_id);
            let nlp_model=self.inference_store.get_model(aconfig.nlp_model.as_ref().unwrap().inference_provider.clone(),&aconfig.nlp_model.as_ref().unwrap().model_id);

            let first_agent=Agent::new(
                    aconfig.agent_name.clone(), 
                    aconfig.agent_name.clone(), 
                    aconfig.backstory.clone(), 
                    HashMap::new(),
                    reasoning_model ,
                    nlp_model ,
                    None,
                    self.app_store.clone(),
                    self.protocols_store.clone(),
                    aconfig.allow_self_selected_apps
                );

            for dapp in &aconfig.default_apps{
                info!("Attaching default app:{} to agent:{}",dapp,agent_name);
                let identified_app=self.app_store.clone_app(dapp.clone());
                if identified_app.is_none(){
                    error!("Default app:{} for agent:{} not found in app store",dapp,agent_name);
                    continue;
                }
                block_on(Agent::ping(&first_agent,AgentPulse::AttachApp(identified_app.unwrap())));
            }
            
            first_agent
        }
        else{
            panic!("No agent named:{} found",agent_name);
        }


    }
}
pub struct Agent{
    agent_card:Source,
    agent_goal:String,
    backstory:String,
    terminal:Arc<Terminal>,
    reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
    nlp_model:Arc<dyn inference_api_trait + Send + Sync>,
    latest_episode_id:RwLock<Option<String>>,
    episodes:Arc<RwLock<HashMap<String,Arc<episode>>>>,
    invoke_post_fn:Option<fn(String,&mut Agent)->MemoryNode>,
    validator_card:Source,
    _agent_tx: channel::Sender<AgentPulse>,
    _agent_rx: channel::Receiver<AgentPulse>,
    app_store:Arc<AppStore>,
    protocols_store:Arc<ProtocolStore>,
    allow_self_selected_apps:bool,
    // _post_invoke_fn:Option<fn(String)->MemoryNode>
}
impl Agent{
    pub fn new(
        agent_name:String,
        agent_goal:String,
        backstory:String,
        agent_info:HashMap<String,String>,
        reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
        nlp_model:Arc<dyn inference_api_trait + Send + Sync>,
        invoke_post_fn:Option<fn(String,&mut Agent)->MemoryNode>,
        app_store:Arc<AppStore>,
        protocols_store:Arc<ProtocolStore>,
        allow_self_selected_apps:bool,
    )->Arc<RwLock<Arc<Self>>>{
        let (tx, rx) = channel::unbounded();
        let agent_card=Source::new(Role::Agent, agent_name.clone(), Some(agent_info));
        
        let episodes=Arc::new(RwLock::new(HashMap::new()));
        let new_agent=Arc::new(RwLock::new(Arc::new(Self{
            agent_card:agent_card.clone(),
            episodes: episodes.clone(),
            agent_goal,
            backstory,
            reasoning_model:reasoning_model.clone(),
            nlp_model:nlp_model.clone(),
            terminal:Arc::new(Terminal::new(Some(app_store.clone()), Some(tx.clone()))),
            latest_episode_id:RwLock::new(None),
            invoke_post_fn,
            validator_card:Source::new(Role::App,format!("{}ResponseValidator",agent_name.clone()),None),
            _agent_tx:tx.clone(),
            _agent_rx:rx.clone(),
            app_store,
            protocols_store,
            allow_self_selected_apps
        })));

        let new_agent_clone=new_agent.clone();
        let agent_rx_clone=rx.clone();

        
        thread::spawn(move || {
                let tokio_rt: tokio::runtime::Runtime  = tokio::runtime::Runtime::new().unwrap();
                let agent_lock = tokio_rt.block_on(new_agent_clone.write());
                info!("Agent thread started. Agent ID: {}", agent_lock.agent_card.get_name());
                drop(agent_lock);

                

                while let Ok(new_pulse) = agent_rx_clone.recv() {
                        let aclone=new_agent_clone.clone();                 
                        
                        // info!("Agent message receive:");
                        match new_pulse{
                            AgentPulse::Invoke(epid)=>{
                               tokio_rt.spawn(Agent::_invoke(aclone, epid));
                                
                            },
                            AgentPulse::NewEpisode(edesc,i_mem,react_for_history)=>{
                                tokio_rt.spawn(Agent::initiate_new_episode(aclone,edesc.clone(),i_mem,react_for_history));
                            },
                            AgentPulse::AttachApp(app)=>{  
                               tokio_rt.spawn(Agent::attach_app(aclone, app));
                            },
                            AgentPulse::lockAgentForEpisode(epid)=>{                            
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    let readble_episode=agent_lock.episodes.read().await;
                                    let req_episode=readble_episode.get(&epid);
                                    match req_episode{
                                        Some(repisode)=>{
                                            repisode.lock_agent().await;
                                        },
                                        None=>{}
                                    }
                                });
                            },
                            AgentPulse::SetAgentFollowupStatus(epid, followup_planned)=>{
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    let readble_episode=agent_lock.episodes.read().await;
                                    let req_episode=readble_episode.get(&epid);
                                    match req_episode{
                                        Some(repisode)=>{
                                            repisode.set_followup_planned(followup_planned).await;
                                        },
                                        None=>{}
                                    }
                                });
                            },
                            AgentPulse::unlockAgentForEpisode(epid)=>{                         
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    let readble_episode=agent_lock.episodes.read().await;
                                    let req_episode=readble_episode.get(&epid);
                                    match req_episode{
                                        Some(repisode)=>{
                                            repisode.unlock_agent().await;
                                        },
                                        None=>{}
                                    }
                                });
                            },
                            AgentPulse::AddMemory(mnode,epid)=>{
                                                          
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    agent_lock.insert(mnode,epid).await;
                                });
                            }
                            AgentPulse::AddMultipleMemories(mnode,epid)=>{         
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    agent_lock.insert_multiple(mnode,epid).await;
                                });
                            }
                            AgentPulse::AddMultipleMemoriesAndInvoke(mnode,epid)=>{
                                                          
                                tokio_rt.spawn(async move{
                                    let agent_lock =aclone.read().await;
                                    agent_lock.insert_multiple(mnode,epid.clone()).await;
                                    drop(agent_lock);
                                    thread::sleep(Duration::from_secs(1));
                                    Agent::_invoke(aclone.clone(), epid).await;
                                });
                            }
                            AgentPulse::UpdateEpisode(last_inode_id,epid)=>{
                                                          
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    agent_lock.update_episode_imemory_lastnodeid(last_inode_id,epid).await;
                                });
                            }
                            AgentPulse::AddMemoryAndInvoke(mnode,epid)=>{
                                                          
                                tokio_rt.spawn(async move{
                                    let agent_lock = aclone.read().await;
                                    agent_lock.insert(mnode,epid.clone()).await;
                                    drop(agent_lock);
                                    thread::sleep(Duration::from_secs(1));
                                    Agent::_invoke(aclone.clone(), epid).await;
                                });

                            }
                            _=>{info!("Unknown pulse:{:?}",new_pulse);}
                        }
                    }
        });   
        
        info!("Launching Episode monitoring thread");
        let episodes_clone=episodes.clone();
        let agent_tx_clone=tx.clone();
        let agent_card_clone=agent_card.clone();
        thread::spawn(move ||{
            let tokio_rt  = tokio::runtime::Runtime::new().unwrap();
            let agent_card=agent_card_clone;

            loop {
                thread::sleep(Duration::from_secs(1));

                let readable_epsiode_memories=tokio_rt.block_on(episodes_clone.read());

                for (episode_id,episode) in readable_epsiode_memories.iter(){
                    

                    if tokio_rt.block_on(episode.get_agent_lock_status()){
                        // info!("Agent locked for episode:{}",episode_id);
                        continue;
                    }
                    if episode.episode_memory._kill_switch.load(Ordering::Relaxed){
                        continue;
                    }
                    // info!("Tick every 1 seconds episode_id {}",episode_id);

                    match &episode.interface_memory{
                        Some(imemory)=>{
                            let last_fetched_imemory_node_id=(*tokio_rt.block_on(episode.last_fetched_imemory_id.lock())).clone();
                            
                            // info!("last_fetched_imemory_node_id:{:?}",last_fetched_imemory_node_id);
                            let incremental_memories:Vec<MemoryNode>=tokio_rt.block_on(imemory.incremental_mem_nodes(last_fetched_imemory_node_id,Some(&agent_card))).collect();
                            
                            if incremental_memories.len()>0{
                                let last_mem=incremental_memories.last();

                                let mut need_invoke=check_for_invoke_trigger(&incremental_memories);
                                if imemory._read_only{
                                    info!("Interface memory is read only, skipping invoke trigger check");
                                    need_invoke=false;
                                }

                                info!("Need incoke:{} - {}",need_invoke,incremental_memories.len());
                                info!("Last me : {:?}",last_mem);
                                
                                if let Some(lastmem)=last_mem{
                                    info!("Sending Update event");
                                    let last_nodeid=lastmem.get_node_id();
                                    agent_tx_clone.send(AgentPulse::UpdateEpisode(last_nodeid.clone(),episode_id.clone())).unwrap();
                                }
                                if need_invoke{
                                    agent_tx_clone.send(AgentPulse::AddMultipleMemoriesAndInvoke(incremental_memories.clone(),Some(episode.episode_id.clone()))).unwrap();
                                }
                                else{
                                    agent_tx_clone.send(AgentPulse::AddMultipleMemories(incremental_memories.clone(),Some(episode.episode_id.clone()))).unwrap();
                                }

                            }
                        }
                        None=>{continue;}
                    }
                }
            }
        });
        // episode_interface_monitor_thread

        // let (episode_tx, episode_rx) = channel::unbounded();

        // thread::spawn({
        //     loop {
        //         if let Ok(_) = rx.try_recv() {
        //             info!("Thread shutting down");
        //             break;
        //         }

        //         info!("Working...");
        //         thread::sleep(Duration::from_secs(1));
        //     }
        // });

        new_agent.clone()
    }

    pub async fn get_episodes(&self)->Vec<Arc<episode>>{
        let episodes=self.episodes.read().await;
        let cloned_episodes =episodes.values().cloned().collect::<Vec<Arc<episode>>>();
        cloned_episodes 
    }
    pub fn clone_reasoning_model(&self)->Arc<dyn inference_api_trait + Send + Sync>{
        self.reasoning_model.clone()
    }
    pub async fn get_tool_select_content(&self,episode_memory:Arc<Memory>,model: Arc<dyn inference_api_trait + Send + Sync>)->String{

        let history_lookup_len=50 as isize;
        let memory_len=episode_memory.get_memory_len().await as isize;

        let mut conv=Vec::new();
        for rec in episode_memory.iter_memory(Some((memory_len-history_lookup_len).max(0) as usize), None,Some(&self.agent_card)).await{
            let mem_node_type=rec.get_node_type();
            if mem_node_type==MemoryNodeType::Message || mem_node_type==MemoryNodeType::Thought || mem_node_type==MemoryNodeType::TerminalCommands{
                conv.push(format!("{}:{}",rec.get_source_role().as_str(),rec.get_content()));
            }
        }

        let raw_conv=conv.join("\n");

        let ner_prompt=self.get_ner_tagging_prompt(raw_conv);
        let new_resp=model.generate(ner_prompt).await;
        info!("NER RESP:{}",new_resp);
        new_resp



    }
    async fn _invoke(new_agent_clone: Arc<RwLock<Arc<Agent>>>,epid: Option<String>){
        
        let agent_lock = new_agent_clone.read().await;

        let latest_episode_id=agent_lock.latest_episode_id.read().await.clone();
        let reasoning_model_clone=agent_lock.reasoning_model.clone();
        let nlp_model_clone=agent_lock.nlp_model.clone();
        let agent_card=agent_lock.agent_card.clone();
        let episode_id=epid.clone();
        let validator_card=agent_lock.validator_card.clone();
        let agent_tx_clone=agent_lock._agent_tx.clone();
        let allow_self_selected_apps=agent_lock.allow_self_selected_apps;
        match &epid{
            Some(eid)=>{
                agent_tx_clone.send(AgentPulse::lockAgentForEpisode(eid.clone())).unwrap();
                match agent_lock.episodes.read().await.get(eid).cloned(){
                    Some(current_episode)=>{
                        let mlen=current_episode.episode_memory.get_memory_len().await;
                        info!("Episode Mem len:{}",mlen);
                        let mut app_chain_str="".to_string();
                        if allow_self_selected_apps{
                            let ner_content=agent_lock.get_tool_select_content(current_episode.episode_memory.clone(),nlp_model_clone.clone()).await;
                            let (tools_select, app_chain_str)=agent_lock.app_store.resolve_tools(current_episode.episode_memory.clone(),ner_content,Some(&agent_card)).await;

                            for app_handle_name in tools_select.iter(){
                                info!("Launching New App:{} | Agent:{}",app_handle_name,agent_card.get_name());
                                let new_app=agent_lock.app_store.clone_app(app_handle_name.clone());
                                if new_app.is_none(){
                                    error!("App:{} not found in app store",app_handle_name);
                                    continue;
                                }
                                agent_lock.terminal.launch_app(new_app.unwrap()).await;
                            }
                        }
                        let current_sys_info=get_sys_info();
                        let agent_prompt=agent_lock.get_sys_prompt(&current_sys_info,&app_chain_str);
                        // info!("Model Prompt :\n{}",agent_prompt);
                        let agent_tof_prompt=agent_lock.get_tof_sys_prompt(&current_sys_info,&app_chain_str);
                        let agent_rac_prompt=agent_lock.get_rac_sys_prompt(&current_sys_info,&app_chain_str);        
                        
                        let terminal=agent_lock.terminal.clone();

                        let interface_memory=current_episode.interface_memory.clone();
                        
                        let mlen=current_episode.episode_memory.get_memory_len().await;
                        info!("Episode Mem len:{}",mlen);
                        let current_episode_memory=current_episode.episode_memory.clone();
                        Agent::invoke(
                            latest_episode_id,
                            current_episode_memory,
                            agent_prompt,
                            agent_tof_prompt,
                            agent_rac_prompt,
                            reasoning_model_clone,
                            nlp_model_clone,
                            agent_card.clone(),
                            epid.clone(),
                            terminal,
                            interface_memory,
                            validator_card.clone(),
                            agent_tx_clone,   
                        ).await;

                    },
                    None=>{}
                }
            }
            None=>{}
        };
    }
    pub async fn attach_app(agent_self:Arc<RwLock<Arc<Agent>>>,app:App){
        let agent_locked=agent_self.read().await.clone();
        agent_locked.terminal.launch_app(app).await;
        drop(agent_locked);

    }

    pub fn get_agent_id(&self)->String{
        self.agent_card.get_id()
    }
    pub fn get_agent_card(&self)->Source{
        self.agent_card.clone()
    }
    
    pub async fn ping(agent_self:&Arc<RwLock<Arc<Self>>>,ping_type:AgentPulse){
        let agent_locked=agent_self.read().await;
        agent_locked._agent_tx.send(ping_type).or_else(|e| Err(e)).unwrap();

    }

    pub async fn update_episode_imemory_lastnodeid(&self,lnodeid:String,episode_id:String){
        info!("Update:{} |epid {}",lnodeid,episode_id);
        let mut writable_episodes=self.episodes.write().await;

        if let Some(ep)=writable_episodes.get_mut(&episode_id){
            ep.set_lastfetch_memoryid(lnodeid).await;
        }
    }
    pub async fn initiate_new_episode(agent_lock: Arc<RwLock<Arc<Agent>>>,episode_desc:String,episode_interface_memory:Option<Arc<Memory>>,react_for_history:bool)->String{
        let agent_self=agent_lock.write().await;
        let mut episode_id=if episode_interface_memory.is_some(){
            episode_interface_memory.as_ref().unwrap().get_branch_id()
        } else {
            Uuid::now_v7().to_string()
        };
        let episode_memory=Memory::new(None,MemoryType::AgentEpisode);
        
        let latest_fetched_id=match &episode_interface_memory{
            Some(mem)=>{
                episode_id=mem.get_branch_id();
                if react_for_history{
                    None
                } else {
                    mem.get_latest_memory_id()
                }
            }
            None=>{None}
        };
        let mut writable_episode=agent_self.latest_episode_id.write().await;
        *writable_episode=Some(episode_id.clone());

        let mut writable_episodes=agent_self.episodes.write().await;    
        writable_episodes.insert(episode_id.clone(), Arc::new(episode { episode_id:episode_id.clone(), episode_memory:episode_memory.clone(),episode_desc,interface_memory:episode_interface_memory,last_fetched_imemory_id:Mutex::new(latest_fetched_id) ,agent_lock:Mutex::new(false),followup_planned:Mutex::new(false) }));
    
        
        info!("New Episode Launched:{}",episode_id);
        episode_id.clone()  
        
    }

    pub async fn insert(&self,memory_node:MemoryNode,episode_id:Option<String>){
        let invoking_episode_id=match &episode_id{
            Some(epid)=>{Some(epid.clone())},
            None=>{
                let epid=self.latest_episode_id.read().await.clone();
                match epid{
                    Some(latest_episode_id)=>{
                        Some(latest_episode_id.clone())
                    }
                    None=>{None}
                }
            }
        };
        
        match &invoking_episode_id{
            Some(invoking_episode_id)=>{
                self.episodes.read().await.get(invoking_episode_id).unwrap().episode_memory.insert(memory_node).await;
            }
            None=>{info!("INSERT:Episode not lauched yet");}

        }
    }
    pub async fn iter_episode_memory(
        agent_lock: Arc<RwLock<Arc<Agent>>>,
        episode_id: String,
        start_index: usize,
        filter_tags: Option<HashSet<String>>,
    ) -> Result<impl Iterator<Item = MemoryNode>, String> {

        let (episode,agent_card) = {
            let readable_agent = agent_lock.read().await;
            let readable_episodes = readable_agent.episodes.read().await;

            (readable_episodes.get(&episode_id).cloned(),readable_agent.agent_card.clone())
        };

        if let Some(ep) = episode {
            let data: Vec<MemoryNode> = ep
                .episode_memory
                .iter_memory(Some(start_index), filter_tags,Some(&agent_card))
                .await
                .into_iter()
                .collect();

            Ok(data.into_iter())   
        } else {
            Err("Episode Id not found in agent".to_string())
        }
    }
    pub async fn insert_multiple(&self,memory_node_vec:Vec<MemoryNode>,episode_id:Option<String>){
        let invoking_episode_id=match &episode_id{
            Some(epid)=>{Some(epid.clone())},
            None=>{
                let epid=self.latest_episode_id.read().await.clone();
                match epid{
                    Some(latest_episode_id)=>{
                        Some(latest_episode_id.clone())
                    }
                    None=>{None}
                }
            }
        };


        
        
        match &invoking_episode_id{
            Some(invoking_episode_id)=>{
                let episode_memory=self.episodes.read().await.get(invoking_episode_id).unwrap().episode_memory.clone();
                for memory_node in memory_node_vec{        
                    episode_memory.insert(memory_node).await;
                }
            }
            None=>{info!("INSERT:Episode not lauched yet");}
     }
    }

    pub async fn print_current_episode(&self){
        
        let epid=self.latest_episode_id.read().await.clone();
        match epid{
            Some(latest_episode_id)=>{
                for i in self.episodes.read().await.get(&latest_episode_id).unwrap().episode_memory.iter_memory(None,None,Some(&self.agent_card)).await{
                    info!("{:?}",i);
                }
            }
            None=>{info!("Print:Episode not lauched yet");}

        }
    }
    pub async fn get_episode_len(&self,episode_id:String)->usize{
        
        let episodes=self.episodes.read().await;
        if episodes.contains_key(&episode_id){
            episodes.get(&episode_id).unwrap().episode_memory.get_memory_len().await

        }
        else{
            info!("Episode not found in agent:{}",episode_id);
            0
        }        
    }
    pub async fn get_agent_episode_status(&self,episode_id:String)->bool{
        
        let episodes=self.episodes.read().await;
        if episodes.contains_key(&episode_id){
            episodes.get(&episode_id).unwrap().get_agent_lock_status().await

        }
        else{
            info!("Episode not found in agent:{}",episode_id);
            false
        }        
    }
    pub async fn detach_episode(&self,episode_id:String){
        
        let episodes=self.episodes.read().await;
        if episodes.contains_key(&episode_id){
            info!("{} detaching",episode_id);
            episodes.get(&episode_id).unwrap().episode_memory.kill_memory();

        }
        
        else{
            info!("Episode not found in agent:{}",episode_id);
        }
    }
    
    fn get_sys_prompt(&self,current_sys_info:&String,app_chain_str:&String)->String{
        // info!("App Guidebook:\n{}",self.terminal.get_app_guidebook());
        // if self.agent_card.get_name()=="Cogitare"{
        //     info!("Using custom prompt for Cogitare : Reasoning Prompt");
        //     return fs::read_to_string("./prompts/AGENT_COGITARE_PROMPT.md").unwrap();
        // }
        
        format!( include_str!("../prompts/AGENT_REASONING_PROMPT.md"),
        agent_name=self.agent_card.get_name(),
        agent_rules=include_str!("../prompts/AGENT_OPERATING_RULES.md"),
        agent_goal=self.agent_goal,
        agent_backstory=self.backstory.clone(),// app_chain_str=app_chain_str,
        app_guidelines=block_on(self.terminal.get_app_guidebook()),
        protocols_book=self.protocols_store.get_protocols_book(),
        current_os_info=current_sys_info,
        knowledge_base_index=fs::read_to_string("./knowledge_base/index.md").unwrap_or_else(|_| "".to_string()))
        
    }

    
    fn get_ner_tagging_prompt(&self,raw_content:String)->String{
        
        format!( include_str!("../prompts/CONTEXT_TAGGING_PROMPT.md"),RAW_CONTENT=raw_content)
        
    }

    fn get_tof_sys_prompt(&self,current_sys_info:&String,app_chain_str:&String)->String{
        // if self.agent_card.get_name()=="Cogitare"{
        //     info!("Using custom prompt for Cogitare : TOF Prompt");
        //     return fs::read_to_string("./prompts/AGENT_COGITARE_PROMPT.md").unwrap();
        // }
        
        
        format!(include_str!("../prompts/AGENT_TOT_PROMPT.md"),
        agent_name=self.agent_card.get_name(),
        agent_rules=include_str!("../prompts/AGENT_OPERATING_RULES.md"),
        agent_goal=self.agent_goal,
        agent_backstory=self.backstory.clone(),// app_chain_str=app_chain_str,
        app_guidelines=block_on(self.terminal.get_app_guidebook()),
        protocols_book=self.protocols_store.get_protocols_book(),
        current_os_info=current_sys_info,
        knowledge_base_index=fs::read_to_string("./knowledge_base/index.md").unwrap_or_else(|_| "".to_string()))
    }

    

    fn get_rac_sys_prompt(&self,current_sys_info:&String,app_chain_str:&String)->String{
        // if self.agent_card.get_name()=="Cogitare"{
        //     info!("Using custom prompt for Cogitare : RAC Prompt");
        //     return fs::read_to_string("./prompts/AGENT_COGITARE_PROMPT.md").unwrap();
        // }
        
        
        format!(include_str!("../prompts/AGENT_RAC_PROMPT.md"),
        agent_name=self.agent_card.get_name(),
        agent_rules=include_str!("../prompts/AGENT_OPERATING_RULES.md"),
        agent_goal=self.agent_goal,
        agent_backstory=self.backstory.clone(),// app_chain_str=app_chain_str,
        app_guidelines=block_on(self.terminal.get_app_guidebook()),
        protocols_book=self.protocols_store.get_protocols_book(),
        current_os_info=current_sys_info,
        knowledge_base_index=fs::read_to_string("./knowledge_base/index.md").unwrap_or_else(|_| "".to_string()))
        // knowledge_base_index=format!(include_str!("../knowledge_base/index.md")))
    }

    async fn handle_error(invoc_id:String,validator_card:&Source,error_ls:Vec<ParseError>,need_rerun:& mut bool ,current_episode_memory:Arc<Memory>,prompt_style:Option<PromptStyle> )->String{
        let mut erro_v=Vec::new();
        let mut combined_error=String::new();
        for e in error_ls{
            // info!("MODEL RESP ERROR {:?}",e);
            match e{
                ParseError::RegexError(e)=>{info!("Regex Error Occured");},
                ParseError::CommandsError(e) | 
                ParseError::ValidationError(e) | 
                ParseError::ThoughtsError(e)| 
                ParseError::OutputError(e) |
                ParseError::FollowupContextError(e) =>{
                    *need_rerun=true;
                    erro_v.push(e);
                }
                _=>{info!("Unknown error:{:?}",e);}
            }
        }

        if erro_v.len()>0{
            combined_error=format!("Errors:\n{}",erro_v.join("\n"));

            info!("Error Identified:\n{}",combined_error);
            current_episode_memory.insert(MemoryNode::new(validator_card,combined_error.clone() , prompt_style, MemoryNodeType::ModelError,Some(invoc_id),None)).await;
        }
        combined_error

    }

    async fn get_pos_tags(nlp_model:Arc<embedder>,mem:Arc<Memory>,source:Option<&Source>)->Vec<String>{
        let memory_len=mem.get_memory_len().await;

        let mut shortlisted_msgs=Vec::new();

        for rec in mem.iter_memory(Some(std::cmp::max(0,memory_len-50)), None, source).await{
            let node_type=rec.get_node_type();
            if node_type==MemoryNodeType::Message || node_type==MemoryNodeType::Message{
                shortlisted_msgs.push(rec.get_content());
            }
        }
        shortlisted_msgs

        // let pos_tags=nlp_model.get_pos_tags(&shortlisted_msgs).await;




    } 

    pub async fn invoke(
        latest_episode_id:Option<String>,
        current_episode_memory:Arc<Memory>,
        agent_prompt:String,
        agent_tof_prompt:String,
        agent_rac_prompt:String,
        reasoning_model_clone: Arc<dyn inference_api_trait + Send + Sync>,
        nlp_model_clone: Arc<dyn inference_api_trait + Send + Sync>,
        agent_card:Source,
        episode_id:Option<String>,
        terminal:Arc<Terminal>,
        interface_memory:Option<Arc<Memory>>,
        validator_card:Source,
        agent_tx:channel::Sender<AgentPulse>
    ){
        let mut need_rerun:bool=true;
        let mut run_count=0;
        const  MAX_RUN_ALLOWED:i32=7;
        // let repair_prompt_template=;
        let mut repair_prompt=String::new();
        let mut parsed_response=ParsedResponse{validation_block:None,thoughts:None,commands:None,outputs:None,followup_context:None,success:false};

        let invoking_episode_id:Option<String>=match &episode_id{
            Some(eid)=>{Some(eid.clone())},
            None=>{
                match &latest_episode_id{
                    Some(cid)=>{Some(cid.clone())}
                    None=>{None}

                }
            }
        };

        let mut invoc_id=Uuid::now_v7().to_string();
        let mut followup_planned=false;

        while need_rerun && run_count<MAX_RUN_ALLOWED {
            
            need_rerun=false;


            if let Some(invoke_epid)= &invoking_episode_id{
                info!("Invoking Model for episode:{}",invoke_epid);
                agent_tx.send(AgentPulse::lockAgentForEpisode(invoke_epid.clone())).unwrap();
                let lookupid:&String=invoke_epid;
                
                let mut choosen_prompt: Option<PromptStyle>;
                let final_agent_prompt=if run_count==0{
                    invoc_id=Uuid::now_v7().to_string();
                    info!("Invoking Reasoning prompt  | Episode Id:{} | Agent :{}|",invoke_epid.clone(),agent_card.get_name());
                    choosen_prompt=Some(PromptStyle::REASONING);
                    agent_prompt.clone()
                }
                else if run_count==1 || run_count==3 || run_count==5{
                    info!("Invoking Repair prompt | Episode Id:{} | Agent :{}|",invoke_epid.clone(),agent_card.get_name());
                    choosen_prompt=Some(PromptStyle::REPAIR);
                    repair_prompt.clone()
                }
                else if run_count==2{
                    invoc_id=Uuid::now_v7().to_string();
                    info!("Invoking RAC prompt | Episode Id:{} | Agent :{}|",invoke_epid.clone(),agent_card.get_name());
                    choosen_prompt=Some(PromptStyle::RAC);
                    agent_rac_prompt.clone()
                }
                else{
                    invoc_id=Uuid::now_v7().to_string();
                    info!("Invoking TOF prompt | Episode Id:{} | Agent :{}|",invoke_epid.clone(),agent_card.get_name());
                    choosen_prompt=Some(PromptStyle::TOF);
                    agent_tof_prompt.clone()
                };
                
                // info!("FINAL PROMPT:{}",final_agent_prompt);
                let resp=reasoning_model_clone.chat(current_episode_memory.clone(),
                final_agent_prompt,
            Some(invoc_id.clone()),Some(&agent_card)).await;
                info!("Model resp:{}",resp);

                agent_tx.send(AgentPulse::AddMemory(MemoryNode::new(&agent_card, resp.clone(),
                                    choosen_prompt.clone(), 
                                    MemoryNodeType::ModelResponse,Some(invoc_id.clone()),None),
                 Some(invoke_epid.clone()))).unwrap();
                
                let mut error_ls:Vec<ParseError>=Vec::new();
                let mut val_block:Option<Validation>=None;
                match AgentResponseParser::parse(&resp){
                    Ok(lval_block)=>{
                        val_block=Some(lval_block);
                        info!("Validation Sucessful:{:?}",val_block);
                        parsed_response.validation_block=val_block.clone();
                    }
                    Err(e)=>{error_ls.push(e);}
                }
                
                match AgentResponseParser::parse_commands(&mut val_block, &resp){
                    Ok(CommandBlock { commands })=>{
                        let commands_errs=terminal.validate_app_commands(&commands).await;
                            if commands_errs.len()>0{
                                error_ls.push(ParseError::CommandsError(commands_errs.join("\n")));
                            }
                            else{
                                info!("Found successful commands {:?}",commands);
                                parsed_response.commands=Some(commands);
                            }
                    },
                    Err(e)=>{error_ls.push(e);}
                }
                
                match AgentResponseParser::parse_thoughts(&mut val_block, &resp) {
                    Ok(ThoughtsBlock{thoughts})=>{
                        info!("found thoughts: {:?}",thoughts);
                        parsed_response.thoughts=Some(thoughts);
                    },
                    Err(e)=>{error_ls.push(e);}  
                }
                match AgentResponseParser::parse_outputs(&mut val_block, &resp) {
                    Ok(OutputsBlock{outputs})=>{
                        info!("found outputs: {:?}",outputs);
                        parsed_response.outputs=Some(outputs);
                    }
                    Err(e)=>{error_ls.push(e);}
                
                }
                match AgentResponseParser::parse_followup_context(&mut val_block, &resp) {
                    Ok(FollowupContextBlock{followup_context    })=>{
                        info!("found followup_context    : {:?}",followup_context    );
                        parsed_response.followup_context =Some(followup_context   );
                    }
                    Err(e)=>{error_ls.push(e);}
                
                }

                if let Some(final_val_block)=&val_block{
                    if !final_val_block.output && !final_val_block.commands && !final_val_block.thoughts{
                        error_ls.push(ParseError::ValidationError("All three of thoughts,terminal,output is set false in validation block.Model cannot response all three false.Analyze and correct your mistakes".to_string()));
                        
                    }
                }

                // match self.invoke(String)_post_fn{

                //     Some(post_fn)=>{(post_fn)(resp.clone());}
                //     None=>{}
                // }
                if error_ls.len()>0{
                    let error_str=Agent::handle_error(invoc_id.clone(),&validator_card,error_ls, &mut need_rerun, current_episode_memory.clone(),choosen_prompt.clone()).await;
                    repair_prompt=format!(include_str!("../prompts/AGENT_RESPONSE_REPAIR_PROMPT.md"),
                        malformed_response=resp,
                        validator_errors=error_str);
                }

                parsed_response.success=!need_rerun;

                if parsed_response.success{
                    if let(Some(validation_block))=&parsed_response.validation_block{
                        if validation_block.needs_followup{
                            followup_planned=true;
                        }
                    }

                    if let Some(outputs)=&parsed_response.outputs{
                        if outputs.len()>0{
                            followup_planned=outputs.iter().any(|o| o.starts_with("/"));
                            let output_memory_node=MemoryNode::new(&agent_card, outputs.join("\n"), None, MemoryNodeType::Message,Some(invoc_id.clone()),None);
                            match &interface_memory{
                                Some(imemory)=>{
                                    if imemory._read_only{
                                        info!("Interface memory is read only, skipping write");
                                    }
                                    else{
                                        info!("Writing to interface memory");
                                        imemory.insert(output_memory_node).await;
                                    }
                                }
                                None=>{}
                            }
                        }
                    }
                    
                    
                    // if let Some(thoughts)=&parsed_response.thoughts{
                    //     if thoughts.len()>0{
                    //         let thoughts_memory_node=MemoryNode::new(&agent_card, thoughts.join("\n"), None, MemoryNodeType::Thought,Some(invoc_id.clone()));
                    //         current_episode_memory.insert(thoughts_memory_node).await;
                    //     }
                    // }
                    
                    if let Some(commands)=&parsed_response.commands{
                        if commands.len()>0{
                            followup_planned=true;
                            let mut filtered_cmds=Vec::new();
                            for comnds in commands.iter(){
                                if comnds.trim().starts_with("/"){
                                    let output_memory_node=MemoryNode::new(&agent_card, comnds.trim().to_string().clone(), None, MemoryNodeType::Message,Some(invoc_id.clone()),None);
                                    match &interface_memory{
                                        Some(imemory)=>{
                                            if imemory._read_only{
                                                info!("Interface memory is read only, skipping write");
                                            }
                                            else{
                                                info!("Writing to interface memory");
                                                imemory.insert(output_memory_node).await;
                                            }
                                        }
                                        None=>{}
                                    }
                                }
                                else{
                                    filtered_cmds.push(comnds.clone());
                                }
                                
                            }
                            
                            
                            // let commands_memory_node=MemoryNode::new(&agent_card, commands.join("\n"), None, MemoryNodeType::TerminalCommands,Some(invoc_id.clone()));
                            // current_episode_memory.insert(commands_memory_node).await;
                            println!("Filtered cmds:{:?}",filtered_cmds);

                            if filtered_cmds.len()>0{
                                terminal.execute_multi_commands(&filtered_cmds,invoke_epid.clone(),invoc_id.clone()).await;
                            }
                        }
                    }
                    // if let Some(outputs)=&parsed_response.outputs{
                    //     if outputs.len()>0{
                    //         let outputs_memory_node=MemoryNode::new(&agent_card, outputs.join("\n"), None, MemoryNodeType::Message,Some(invoc_id.clone()));
                    //         current_episode_memory.insert(outputs_memory_node).await;
                    //     }
                    // }
                    // if let Some(followupcontext)=&parsed_response.followup_context{
                    //     if followupcontext.len()>0{
                    //         let followupcontext_memory_node=MemoryNode::new(&agent_card, followupcontext.join("\n"), None, MemoryNodeType::FollowupContext,Some(invoc_id.clone()));
                    //         current_episode_memory.insert(followupcontext_memory_node).await;
                    //     }
                    // }
                    // if let Some(validationblock)=&parsed_response.validation_block{
                    //     let validationblock_memory_node=MemoryNode::new(&agent_card, validationblock.to_string(), None, MemoryNodeType::ValidationBlock,Some(invoc_id.clone()));
                    //     current_episode_memory.insert(validationblock_memory_node).await;
                        
                    // }
                    
                    agent_tx.send(AgentPulse::AddMemory(MemoryNode::new(&agent_card, resp.clone(),
                                        choosen_prompt.clone(), 
                                        MemoryNodeType::Message,Some(invoc_id.clone()),None),
                    Some(invoke_epid.clone()))).unwrap();
                    
                }
                    
                if !(need_rerun && run_count<MAX_RUN_ALLOWED){
                    info!("Unlocking agent for episode:{}",lookupid);
                    
                    agent_tx.send(AgentPulse::unlockAgentForEpisode(invoke_epid.clone())).unwrap();
                    agent_tx.send(AgentPulse::SetAgentFollowupStatus(invoke_epid.clone(),followup_planned.clone())).unwrap();

                    break;
                }

            }
            else{info!("Episode not lauched yet");}
            
            if need_rerun{
                info!("Re running:{}",run_count);
                // info!("Waiting sleeping");

                // sleep(Duration::from_secs(20));
                run_count+=1;
            }
            
            

        }
        
        
        info!("Last rerun:{}",need_rerun);

        if !parsed_response.success{
            let error_message=MemoryNode::new(&agent_card, "Error Processing Last Message.Please try again".to_string(), None, MemoryNodeType::Error,Some(invoc_id.clone()),None);
            match &interface_memory{
                Some(imemory)=>{
                    if imemory._read_only{
                        info!("Interface memory is read only, skipping write");
                    }
                    else{
                        info!("Writing Error to interface memory");
                        imemory.insert(error_message).await;
                    }
                }
                None=>{}
            }
        }

        

        

    }
}

pub struct ParsedResponse{
    pub validation_block:Option<Validation>,
    pub commands:Option<Vec<String>>,
    pub outputs:Option<Vec<String>>,
    pub thoughts:Option<Vec<String>>,
    pub followup_context:Option<Vec<String>>,
    pub success:bool
}

#[derive(Debug)]
pub enum ParseError {
    RegexError(String),
    ValidationError(String),
    CommandsError(String),
    ThoughtsError(String),
    OutputError(String),
    FollowupContextError(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Validation {
    pub thoughts: bool,
    pub commands: bool,
    pub output: bool,
    pub needs_followup: bool,
    pub followup_context:bool,
}
impl Validation {
    pub fn to_string(&self)->String{
        format!("thoughts={}\nterminal={}\noutput={}\nfollowup_context={}\nneeds_followup={}",self.thoughts,self.commands,self.output,self.followup_context,self.needs_followup)
    }
}
#[derive(Debug, Clone, PartialEq)]
pub struct CommandBlock {
    pub commands: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ThoughtsBlock {
    pub thoughts: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FollowupContextBlock {
    pub followup_context: Vec<String>,
}


#[derive(Debug, Clone, PartialEq)]
pub struct OutputsBlock {
    pub outputs: Vec<String>,
}


pub struct AgentResponseParser;

impl AgentResponseParser  {
    pub fn parse(resp:&String) -> Result<Validation, ParseError>{
        if resp.trim().len()==0{
            Err(ParseError::ValidationError("Response is empty.".to_string()))
        }
        else{Self::extract_validation_block(resp)}
    }

    fn extract_validation_block(resp:&String) -> Result<Validation, ParseError>{
        let v_block_pattern=r"```\s*\n?validation\s*\n?([\s\S]*?)```";
        let re= Regex::new(v_block_pattern).map_err(|e: regex::Error| ParseError::RegexError(e.to_string()))?;

        let mut error_ls:Vec<String>=Vec::new();

        let matches:Vec<_> = re.captures_iter(resp).collect();
        let re_iter_count=matches.len();
        if re_iter_count==0{
            // return Ok(Validation{thoughts:false,commands:false,output:false,needs_followup:false,followup_context:false});
            Err(ParseError::ValidationError("No Validation block found in your response.Validation block is required.".to_string()))
        }
        else if re_iter_count>1 {
            Err(ParseError::ValidationError("Multiple Validation Block found. Only one is allowed".to_string()))
            
        }
        else{
            
            if let Some(m) =matches[0].get(1) {
                return Self::parse_val_string(m.as_str().trim().to_string());
            }
            else{
                Err(ParseError::ValidationError("Validation Block Parsing Error.Check Validation block".to_string()))
            }

        }

    }
    fn parse_val_string(val_string:String)->Result<Validation,ParseError>{
        let mut val_block=Validation{thoughts:false,commands:false,output:false,needs_followup:false,followup_context:false};
        let mut error_ls=Vec::new();
        for line in val_string.lines(){
            let trimmed=line.trim();
            if trimmed.is_empty(){
                error_ls.push("No Validation Tag found. Must include thoughts=True|False\nterminal=True|False\noutput=True|False\nfollowup_context=True|False\nneeds_followup=True|False\n".to_string());
            }

            if let(Some((key,value)))=line.split_once("="){
                let key=key.trim().to_lowercase();
                let value=value.trim().to_lowercase();
                let mut bool_value:bool=false;
                match value.as_str(){
                    "true"=>{bool_value=true;},
                    "false"=>{bool_value=false;}
                    _=>{
                        error_ls.push(format!("Incorrect validation tag:{}",line));
                    }
                }
                match key.as_str() {
                    "thoughts"=>{val_block.thoughts=bool_value;},
                    "terminal"=>{val_block.commands=bool_value;},
                    "output"=>{val_block.output=bool_value;},
                    "followup_context"=>{val_block.followup_context=bool_value;},
                    "needs_followup"=>{val_block.needs_followup=bool_value;}                    
                    _=>{} //error_ls.push(format!("Unknown validation tag given: {}",line));

                }
            }
            else{
                error_ls.push(format!("Validation block not in right format : {}. Expected format thoughts=True|False\nterminal=True|False\noutput=True|False\nfollowup_context=True|False\nneeds_followup=True|False\n",line));

            }

            
        }
        
        // if !val_block.commands && val_block.needs_followup{
        //     error_ls.push("terminal is set false but needs_followup is set true  in validation block. Why followup is needed when no terminal command is given.Analyze and provide new corrected response".to_string());
            
        // }
        if error_ls.len()>0{
            Err(ParseError::ValidationError(error_ls.join("\n")))
        }
        else {
            Ok(val_block)
        }



    }
    
    pub fn parse_commands(validation:&mut Option<Validation>,resp:&String)->Result<CommandBlock, ParseError>{
        if resp.trim().len()==0{
            Err(ParseError::ValidationError("Response is empty.".to_string()))
        }
        else{Self::extract_commands_block(validation,resp)}

    }
    fn extract_commands_block(validation:&mut Option<Validation>,resp:&String) -> Result<CommandBlock, ParseError>{
        let c_block_pattern=r"```\s*\n?terminal\s*\n?([\s\S]*?)```";
        let re= Regex::new(c_block_pattern).map_err(|e: regex::Error| ParseError::RegexError(e.to_string()))?;

        let mut error_ls:Vec<String>=Vec::new();

        let matches:Vec<_> = re.captures_iter(resp).collect();
        
        let commands_strings: Vec<_> = matches.iter().filter_map(|m| {
            m.get(1).map(|cap| cap.as_str().trim().to_string()).filter(|s| !s.is_empty())
        }).collect();

        let re_iter_count=commands_strings.len();
        if let Some(v_block)=validation{
            if re_iter_count==0 && v_block.commands{
                v_block.commands=false;
                return Err(ParseError::CommandsError("No or empty terminal block found in your response But found terminal=True in v_block block.Analyze and correct your mistakes and set terminal=True|False correctly based on your new response".to_string()));
            }
            // if re_iter_count==0 && v_block.needs_followup{
            //     v_block.commands=false;
            //     return Err(ParseError::CommandsError("No or empty terminal block found in your response But found needs_followup=True in validation block.Why followup needed when no app command is given.Analyze and correct your mistakes and set needs_followup=True|False correctly based on your new response".to_string()));
            // }
            if re_iter_count>0  && !v_block.commands{
                v_block.commands=true;
                // return Err(ParseError::CommandsError("terminal block found in your response But found terminal=False in validation block.Analyze and correct your mistakes and set terminal=True|False correctly based on your new response".to_string()));
            }
        }
        if re_iter_count>0{

            Self::parse_commands_string(commands_strings,validation)
        }
        else{
            Ok(CommandBlock{commands:Vec::new()})
        }
    }

    fn parse_commands_string(command_strings:Vec<String>,validation:&Option<Validation>)->Result<CommandBlock,ParseError>{
        let mut commands:Vec<String>=Vec::new();
        let mut error_ls=Vec::new();
        
        let mut command_strings_splitted = Vec::new();

        for s in command_strings {
            let mut start = 0;
            // Iterate through characters and their byte indices
            for (idx, c) in s.char_indices() {
                if c == '\n' {
                    // For newline, push current part and skip the '\n'
                    if start < idx {
                        command_strings_splitted.push(s[start..idx].to_string());
                    }
                    start = idx + 1;
                } 
                // else if c == '&' && idx > 0 {
                //     // For '&', push current part, then start next part from '&'
                //     if start < idx {
                //         command_strings_splitted.push(s[start..idx].to_string());
                //     }
                //     start = idx;
                // }
            }
            // Push the final remaining part of the string
            if start < s.len() {
                command_strings_splitted.push(s[start..].to_string());
            }
        }

        for line in command_strings_splitted{
            let trimmed=line.trim();
            if trimmed.is_empty(){
                continue;
            }
            if !(line.starts_with("&") || line.starts_with("/")){
                error_ls.push(format!("{} commands did not start with & or /. Valid command format is &<app_name> or /<protocol_name>.Analyze and correct your mistakes",line));
            }
            else{
                commands.push(line);
            }
        }
        if let Some(v_block)=validation{
            if commands.len()==0 && v_block.commands{
                error_ls.push("No valid commands found in terminal block but found terminal=True in validation Block.Analyze and correct your mistakes and set terminal=True|False correctly based on your new response".to_string());

            }
        }
        if error_ls.len()>0{
            Err(ParseError::CommandsError(error_ls.join("\n")))
        }
        else {
            Ok(CommandBlock { commands })
        }
    }
    
            
    pub fn parse_thoughts(validation:&mut Option<Validation>,resp:&String)->Result<ThoughtsBlock, ParseError>{
        if resp.trim().len()==0{
            Err(ParseError::ValidationError("Response is empty.".to_string()))
        }
        else{Self::extract_thoughts_block(validation,resp)}

    }

    fn extract_thoughts_block(validation:&mut Option<Validation>,resp:&String) -> Result<ThoughtsBlock, ParseError>{
        let c_block_pattern=r"```\s*\n?thoughts\s*\n?([\s\S]*?)```";
        let re= Regex::new(c_block_pattern).map_err(|e: regex::Error| ParseError::RegexError(e.to_string()))?;

        let mut error_ls:Vec<String>=Vec::new();

        let matches:Vec<_> = re.captures_iter(resp).collect();
        
        let thoughts_strings: Vec<_> = matches.iter().filter_map(|m| {
            m.get(1).map(|cap| cap.as_str().trim().to_string()).filter(|s| !s.is_empty())
        }).collect();

        let re_iter_count=thoughts_strings.len();
        if let Some(v_block)=validation{
            if re_iter_count==0 && v_block.thoughts{
                v_block.thoughts=false;
                // return Err(ParseError::ThoughtsError("No or empty thoughts block found in your response But found thoughts=True in validation block.Analyze and correct your mistakes and set thoughts=True|False correctly based on your new response".to_string()));
            }
            if re_iter_count>0  && !v_block.thoughts{
                v_block.thoughts=true;
                // return Err(ParseError::ThoughtsError("thoughts block found in your response But found thoughts=False in validation block.Analyze and correct your mistakes and set thoughts=True|False correctly based on your new response".to_string()));
            }
        }
        if re_iter_count>0{

            Ok(ThoughtsBlock{thoughts:thoughts_strings})
        }
        else{
            Ok(ThoughtsBlock{thoughts:Vec::new()})
        }
    }

          
    pub fn parse_outputs(validation:&mut Option<Validation>,resp:&String)->Result<OutputsBlock, ParseError>{
        if resp.trim().len()==0{
            Err(ParseError::ValidationError("Response is empty.".to_string()))
        }
        else{Self::extract_output_block(validation,resp)}

    }

    fn extract_output_block(validation:&mut Option<Validation>,resp:&String) -> Result<OutputsBlock, ParseError>{
        let c_block_pattern=r"```\s*\n?output\s*\n?([\s\S]*?)```";
        let re= Regex::new(c_block_pattern).map_err(|e: regex::Error| ParseError::RegexError(e.to_string()))?;

        let mut error_ls:Vec<String>=Vec::new();

        let matches:Vec<_> = re.captures_iter(resp).collect();

        
        let outputs_string: Vec<_> = matches.iter().filter_map(|m| {
            m.get(1).map(|cap| cap.as_str().trim().to_string()).filter(|s| !s.is_empty())
        }).collect();

        let re_iter_count=outputs_string.len();

        if let Some(v_block)=validation{
            if re_iter_count==0 && v_block.output{
                v_block.output=false;
                // return Err(ParseError::OutputError("No or empty output block found in your response But found output=True in validation block.Analyze and correct your mistakes and set output=True|False correctly based on your new response.".to_string()));
            }
            if re_iter_count>0  && !v_block.output{
                v_block.output=true;
                // return Err(ParseError::OutputError("output block found in your response But found output=False in validation block.Analyze and correct your mistakes and set output=True|False correctly based on your new response".to_string()));
            }
        }
        if re_iter_count>0{

            Ok(OutputsBlock{outputs:outputs_string})
        }
        else{
            Ok(OutputsBlock{outputs:Vec::new()})
        }
    }

    pub fn parse_followup_context(validation:&mut Option<Validation>,resp:&String)->Result<FollowupContextBlock, ParseError>{
        if resp.trim().len()==0{
            Err(ParseError::ValidationError("Response is empty.".to_string()))
        }
        else{Self::extract_followup_context_block(validation,resp)}

    }

    

    fn extract_followup_context_block(validation:&mut Option<Validation>,resp:&String) -> Result<FollowupContextBlock, ParseError>{
        let c_block_pattern=r"```\s*\n?followup_context\s*\n?([\s\S]*?)```";
        let re= Regex::new(c_block_pattern).map_err(|e: regex::Error| ParseError::RegexError(e.to_string()))?;

        let mut error_ls:Vec<String>=Vec::new();

        let matches:Vec<_> = re.captures_iter(resp).collect();
        

        let followup_context_strings: Vec<_> = matches.iter().filter_map(|m| {
            m.get(1).map(|cap| cap.as_str().trim().to_string()).filter(|s| !s.is_empty())
        }).collect();

        let re_iter_count=followup_context_strings.len();
        
        if let Some(v_block)=validation{
            if re_iter_count==0 && v_block.needs_followup{
                v_block.needs_followup=false;
                return Err(ParseError::FollowupContextError("No or empty followup context block found in your response But found needs_followup=True in validation block.Analyze and correct your mistakes and set needs_followup=True|False correctly based on your new response".to_string()));
            }
            if re_iter_count==0 && v_block.followup_context{
                v_block.needs_followup=false;
                return Err(ParseError::FollowupContextError("No or empty followup context block found in your response But found followup_context=True in validation block.Analyze and correct your mistakes and set followup_context=True|False correctly based on your new response".to_string()));
            }
            if re_iter_count>0  && !v_block.needs_followup{
                v_block.needs_followup=true;
                // return Err(ParseError::FollowupContextError("followup_context block found in your response But found needs_followup=False in validation block.Analyze and correct your mistakes and set needs_followup=True|False correctly based on your new response".to_string()));
            }
            if re_iter_count>0  && !v_block.needs_followup{
                v_block.needs_followup=true;
                // return Err(ParseError::FollowupContextError("followup_context block found in your response But found followup_context=False in validation block.Analyze and correct your mistakes and set followup_context=True|False correctly based on your new response".to_string()));
            }
        }
        if re_iter_count>0{
            Ok(FollowupContextBlock{followup_context:followup_context_strings})
        }
        else{
            Ok(FollowupContextBlock{followup_context:Vec::new()})
        }
    }

}
