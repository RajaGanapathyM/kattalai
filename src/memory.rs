use arc_swap::ArcSwap;
use chrono::{DateTime, Utc};
use crossbeam::channel;
use crate::app;
use crate::source::Source;
use crate::agent::{Agent, AgentPulse};
use crate::protocol::ProtocolStore;
use env_logger::filter;
use crate::appstore::AppStore;
use crate::config::InferenceStore;

use regex::Regex;
use std::ptr::read;
use std::sync::{Arc,RwLock};
use std::{
    clone,
    collections::{HashMap, HashSet},
    thread,
};
use uuid::Uuid;
use log::{info, warn, error, debug, trace};
use crate::source::{self, Role};
// use crate::source::Source;
use crate::agent::PromptStyle;
use crate::embeddings::GLOBAL_EMBEDDER;
use std::sync::atomic::{AtomicBool, Ordering};
use futures::executor::block_on;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use tokio::time::{sleep, Duration};
use cron::Schedule;
use std::str::FromStr;
use pyo3::prelude::*;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum IOPhase {
    In,
    Out,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum MemoryNodeType {
    Perception,
    Thought,
    Decision,
    Action,
    Protocol,
    ProtocolLog,
    ProtocolPrompt,
    TerminalCommands,
    ModelResponse,
    AppResponse,
    Error,
    ModelError,
    Message,
    Signal,
    Applog,
    FollowupContext,
    ValidationBlock,
}
impl MemoryNodeType {
    fn as_str(&self) -> &'static str {
        match self {
            MemoryNodeType::Perception=>"Perception",
            MemoryNodeType::Thought=>"Thought",
            MemoryNodeType::Decision=>"Decision",
            MemoryNodeType::Action=>"Action",
            MemoryNodeType::Protocol=>"Protocol",
            MemoryNodeType::ProtocolPrompt=>"ProtocolPrompt",
            MemoryNodeType::TerminalCommands=>"TerminalCommands",
            MemoryNodeType::ModelResponse=>"ModelResponse",
            MemoryNodeType::AppResponse=>"AppResponse",
            MemoryNodeType::ProtocolLog=>"ProtocolLog",
            MemoryNodeType::Error=>"Error",
            MemoryNodeType::ModelError=>"ModelError",
            MemoryNodeType::Message=>"Message",
            MemoryNodeType::Signal=>"Signal",
            MemoryNodeType::Applog=>"Applog",
            MemoryNodeType::FollowupContext=>"FollowupContext",
            MemoryNodeType::ValidationBlock=>"ValidationBlock",
        }
    }
}

#[derive(Clone, Debug)]
pub struct MemoryNode {
    pub node_id: String,
    source: Source,
    timestamp: DateTime<Utc>,
    content: String,
    prompt_info: Option<PromptStyle>,
    node_type: MemoryNodeType,
    branch_id: Option<String>,
    tags: HashSet<String>,
    intents: HashSet<String>,
    invocation_id:Option<String>,
    target:Option<Source>
}
impl MemoryNode {
    pub fn new(
        source: &Source,
        content: String,
        prompt_info: Option<PromptStyle>,
        node_type: MemoryNodeType,
        invocation_id:Option<String>,
        target:Option<&Source>
    ) -> Self {

        let mut tags: HashSet<String>    =HashSet::new();
        let mut actions:HashSet<String>=HashSet::new();

        let embedder=GLOBAL_EMBEDDER.get();
        if let Some(emb)=embedder{
            let pos_model=block_on(emb.get_pos_tags(&vec![content.clone()]));
            let pos_tags=&pos_model[0];
            let (tag,action)=pos_model[0].clone();
            tags.extend(tag.clone().iter().cloned());
            actions.extend(action.clone().iter().cloned());
            
        }
        // info!("{},{:?}",content,tags);


        MemoryNode {
            node_id: Uuid::now_v7().to_string(),
            branch_id: None,
            source: source.clone(),
            timestamp: Utc::now(),
            node_type,
            content,
            prompt_info: prompt_info,
            tags,
            intents:actions,
            invocation_id,
            target: target.cloned(),
        }
    }
    pub fn is_allowed(&self, allowed_roles: &HashSet<Role>) -> bool {
        allowed_roles.contains(&self.source.get_role())
    }
    pub fn get_source_name(&self)->String{
        self.source.get_name().clone()
    }
    pub fn get_invocation_id(&self)->Option<String>{
        self.invocation_id.clone()
    }
    pub fn get_node_type(&self)->MemoryNodeType{
        self.node_type.clone()
    }
    pub fn get_source_role(&self)->Role{
        self.source.get_role().clone()
    }
    pub fn get_content(&self)->String{
        self.content.clone()
    }
    pub fn get_node_tags(&self)->HashSet<String>{
        self.tags.clone()
    }
    pub fn get_node_intents(&self)->HashSet<String>{
        self.intents.clone()
    }

    pub fn get_node_id(&self)->String{
        self.node_id.clone()
    }
    pub fn get_payload(&self, non_tool_roles: &HashSet<Role>) -> serde_json::Value {
        let msg_role=&self.source.get_role();
        serde_json::json!({
            "role": if non_tool_roles.contains(&msg_role) {
                msg_role.as_str()
            } else {
                "tool"
            },
            "name": self.source.get_name(),
            "timestamp": self.timestamp.to_rfc3339(),
            "content": self.content,
        })
    }
    pub fn get_json(&self) -> serde_json::Value {
        let msg_role=&self.source.get_role();
        serde_json::json!({
            "role": msg_role.as_str(),
            "name": self.source.get_name(),
            "timestamp": self.timestamp.to_rfc3339(),
            "content": self.content,
            "node_type":self.node_type.as_str()
        })
    }
}

#[derive(Debug)]
struct MemoryStore {
    mem_vec: ArcSwap<Vec<Arc<MemoryNode>>>,
    mem_indx: Arc<RwLock<HashMap<String, usize>>>,
    tags_indx: Arc<RwLock<HashMap<String, Vec<String>>>>,
}
impl MemoryStore {
    pub fn new() -> Arc<Self> {
        Arc::new(MemoryStore {
            mem_vec: ArcSwap::from_pointee(Vec::new()),
            mem_indx: Arc::new(RwLock::new(HashMap::new())),
            tags_indx: Arc::new(RwLock::new(HashMap::new())),
        })
    }
}

#[derive(Debug)]
pub struct Memory {
    pub _memory_id: String,
    _memory_store: Arc<MemoryStore>,
    _branch_id: String,
    _memory_tx: channel::Sender<AgentPulse>,
    pub _kill_switch:Arc<AtomicBool>
}

impl Memory {
    /// construct a new Memory container
    pub fn new(protocol_store: Option<Arc<ProtocolStore>>) -> Arc<Self> {
        let (tx, rx) = channel::unbounded();
        let arc_memory = Arc::new(Memory {
            _memory_id: Uuid::now_v7().to_string(),
            _memory_store: MemoryStore::new(),
            _branch_id: Uuid::now_v7().to_string(),
            _memory_tx: tx,
            _kill_switch:Arc::new(AtomicBool::new(false))
        });

        let rx_clone = rx.clone();
        let arc_memory_clone = arc_memory.clone();
        let thread_protocol_store = protocol_store.clone();

        thread::spawn(move || {
            let tokio_rt_new: tokio::runtime::Runtime  = tokio::runtime::Runtime::new().unwrap();
            info!("Memory thread started. Memory ID: {}, Branch ID: {}", arc_memory_clone._memory_id, arc_memory_clone._branch_id);
            while let Ok(pulse_node) = rx_clone.recv() {
                let tokio_rt_handle=tokio_rt_new.handle();
                
                let mut new_node = match pulse_node{
                    AgentPulse::AddMemory(mem_node,_)=>mem_node,
                    AgentPulse::AddMemoryAndInvoke(mem_node, _)=>mem_node,  
                    _=>continue
                };
                match &new_node.branch_id{
                    Some(_)=>{},
                    None=>{
                        new_node.branch_id=Some(arc_memory_clone._branch_id.clone());
                    }
                }
                let new_node_content=new_node.get_content();
                // println!("Inserting Memory Node: {:?}", new_node);
                let kill_switch = arc_memory_clone._kill_switch.load(Ordering::Relaxed);
                // println!("kill{:?}",kill_switch);
                if kill_switch{
                    info!("Killing Memory ID:{}", arc_memory_clone._memory_id);
                    break
                }

                let loaded_mem_vec = arc_memory_clone._memory_store.mem_vec.load_full();
                let mut writable_mem_vec = (*loaded_mem_vec).clone();
                let new_node_id=new_node.node_id.clone();
                let new_node_tags=new_node.tags.clone();

                writable_mem_vec.push(Arc::new(new_node));
                let mem_len=writable_mem_vec.len();
                arc_memory_clone._memory_store.mem_vec.store(Arc::new(writable_mem_vec));

                let mut writable_mem_index=arc_memory_clone._memory_store.mem_indx.write().unwrap();
                writable_mem_index.insert(
                    new_node_id.clone(),
                    mem_len-1,
                );

                drop(writable_mem_index);

                let mut writable_tags_indx = arc_memory_clone._memory_store.tags_indx.write().unwrap();

                for tag in &new_node_tags {
                    writable_tags_indx
                        .entry(tag.clone())
                        .or_default()
                        .push(new_node_id.clone());
                }
                drop(writable_tags_indx);

                if let Some(protocol_store_clone) = thread_protocol_store.clone(){
                 
                    if new_node_content.starts_with("/"){
                        let regcap = Regex::new(r"^/([^\s]+)\s+--(schedule|run)(?:\s+(.*))?$").unwrap().captures(&new_node_content);

                        if let Some(caps) = regcap {
                            let command = caps.get(1).map_or("", |m| m.as_str());
                            let action = caps.get(2).map_or("", |m| m.as_str());
                            let arg = caps.get(3).map_or("", |m| m.as_str());

                            if action == "run" {
                                println!("Triggering protocol for node content: {}", new_node_content);
                                tokio_rt_handle.block_on(protocol_store_clone.trigger_protocol(command.to_string(), arc_memory_clone.clone() ));
                            } else if action == "schedule" {
                                println!("Scheduling protocol for node content: {}-{}", command,arg);
                                tokio_rt_handle.block_on(protocol_store_clone.schedule_protocol(&command,&arg,arc_memory_clone.clone()));
                            }
                            else{
                                tokio_rt_handle.block_on(protocol_store_clone.handle_unknown_cmd(&new_node_content, arc_memory_clone.clone()));
                            }
                        }
                        else{
                            println!("No regex match for protocol command in node content: {}", new_node_content);
                        }                        
                    }
                }
            }
        });

        if protocol_store.is_some(){

            let memory_id_clone=arc_memory._memory_id.clone();
            let new_protocol_store_clone=protocol_store.clone().unwrap();
            let new_arc_memory_clone=arc_memory.clone();
            tokio::spawn(async move {
                let file_path = "./configs/protocol_schedules.txt";
                let new_protocol_store=new_protocol_store_clone;
                let my_memory_id=memory_id_clone;
                let my_arc_memory=new_arc_memory_clone;
                println!("Started protocol schedule checker for Memory ID: {}", my_memory_id);

                loop {
                    // println!("Checking scheduled protocols for Memory ID: {}", my_memory_id);
                    if let Ok(file) = fs::File::open(file_path) {
                        let reader = BufReader::new(file);
                        
                        for line in reader.lines() {
                            if let Ok(content) = line {
                                let parts: Vec<&str> = content.split('|').collect();
                                
                                if let Some(memory_id) = parts.get(0) {
                                    if memory_id == &my_memory_id {
                                        if let Some(schedule_string) = parts.get(1) {
                                            if let Some(handle_name)=parts.get(2){
                                                if should_trigger(schedule_string) {
                                                    println!("Triggering scheduled protocol: {} for memory_id: {}", schedule_string, my_memory_id);
                                                    new_protocol_store.trigger_protocol(handle_name.to_string(), my_arc_memory.clone()).await;                                                        
                                                }
                                            }                                                
                                        }
                                    }
                                }
                            }
                        }
                        // let _ = fs::write(file_path, ""); 
                    }
                    sleep(Duration::from_secs(1)).await;
                }
            });
        }

        arc_memory
    }
    pub fn get_memory_tx(&self) -> Option<channel::Sender<AgentPulse>> {
        Some(self._memory_tx.clone())
    }   
    pub fn kill_memory(&self){
        // let kill_switch=self._kill_switch.load_full();
        let kill_ac=self._kill_switch.store(true,Ordering::Relaxed);

    }  
    
    pub async fn incremental_mem_nodes(&self,ref_node_id:Option<String>,source:Option<&Source>)-> impl Iterator<Item = MemoryNode>{
        if let Some(ref_nid)=&ref_node_id{
            let readable_mem_indx=self._memory_store.mem_indx.read().unwrap();

            let ref_indx=readable_mem_indx.get(ref_nid).cloned();
            drop(readable_mem_indx);
            match ref_indx{
                Some(ref_ix)=>{
                    self.iter_memory(Some(ref_ix+1),None,source).await
                }
                None=>{
                    self.iter_memory(None,None,source).await
                }
            }

        }
        else{
            self.iter_memory(None,None,source).await
        }
    }

    pub fn get_latest_memory_id(&self)->Option<String>{
    
        let readable_memvec=self._memory_store.mem_vec.load();

        let last_element=readable_memvec.last();

        if let Some(last_memory_node)=last_element{
            Some(last_memory_node.node_id.clone())
        }
        else{
            None
        }

    }
    pub fn branch(&self) -> Arc<Self> {
        Arc::new(Memory {
            _memory_id: self._memory_id.clone(),
            _memory_store: self._memory_store.clone(),
            _branch_id: Uuid::now_v7().to_string(),
            _memory_tx: self._memory_tx.clone(),
            _kill_switch:Arc::new(AtomicBool::new(false))
        })
    }

    pub async fn get_memory_len(&self) -> usize {
        self._memory_store.mem_vec.load().len()
    }

    /// append an entry
    pub async fn insert(& self, memory_node: MemoryNode) {
        let mut memory_node = memory_node.clone();
        memory_node.branch_id = Some(self._branch_id.clone());

        // create node asynchronously (currently synchronous)
        self._memory_tx.send(AgentPulse::AddMemory(memory_node,None)).unwrap();
    }

    pub async fn get_distinct_node_tags(&self) -> Vec<String> {
        let readable_tag_indx = self._memory_store.tags_indx.read().unwrap();
        readable_tag_indx.keys().cloned().collect()
    }

    pub async fn iter_memory(
        &self,
        start_index:Option<usize>,
        filter_tags: Option<HashSet<String>>,
        source:Option<&Source>
    ) -> impl Iterator<Item = MemoryNode> {
        let local_mem_vec = self._memory_store.mem_vec.load();
        // print!("mem_vec : {}", mem_vec.len());

        let skip_len=match start_index{
            Some(sl)=>{sl}
            None=>{0}
        };
        local_mem_vec
        .iter()
        .skip(skip_len)
        .filter(move |node| {
            let filter_bool=node.branch_id == Some(self._branch_id.clone()) 
                && match &filter_tags {
                    Some(tags) => !node.tags.is_disjoint(tags),
                    None => true,
                }

                && match &node.target {
                    Some(tgt) => {
                        match source {
                            Some(src) => {
                                // println!("Filtering node with target: {:?} against source: {:?}", tgt, src);
                                src.get_role()==source::Role::Runtime || tgt.get_id() == src.get_id()},
                            None => false
                        }
                    }
                    None =>  true
                };
                //  println!("Filtering node: {:?}-{}", node,filter_bool);
                filter_bool
        }).map(|node| node.as_ref().clone()).collect::<Vec<_>>().into_iter()
    }

    /// lookup by id; note lifetime must be propagated through async
    pub async fn get_memorynode_by_id(& self, memory_id: &str) -> Option<MemoryNode> {
        let local_mem_vec = self._memory_store.mem_vec.load();
        let readble_mem_indx=self._memory_store.mem_indx.read().unwrap();
        if let Some(&index) = readble_mem_indx.get(memory_id) {
            Some((*local_mem_vec[index]).clone())
        } else {
            None
        }
    }
}




fn should_trigger(schedule_string: &str) -> bool {
    if let Ok(schedule) = Schedule::from_str(schedule_string) {
        let now = Utc::now();
        
        if let Some(next_event) = schedule.upcoming(Utc).next() {
            let diff = next_event.signed_duration_since(now).num_seconds();
            return diff <= 0; 
        }
    }
    false
}

