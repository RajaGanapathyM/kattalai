use arc_swap::ArcSwap;
use chrono::{DateTime, Utc};
use crossbeam::channel;
use env_logger::filter;
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
use crate::source::Source;
use crate::agent::PromptStyle;
use crate::embeddings::GLOBAL_EMBEDDER;
use std::sync::atomic::{AtomicBool, Ordering};
use futures::executor::block_on;

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
    TerminalCommands,
    ModelResponse,
    AppResponse,
    Error,
    ModelError,
    Message,
    Signal,
    Applog,
}
impl MemoryNodeType {
    fn as_str(&self) -> &'static str {
        match self {
            MemoryNodeType::Perception=>"Perception",
            MemoryNodeType::Thought=>"Thought",
            MemoryNodeType::Decision=>"Decision",
            MemoryNodeType::Action=>"Action",
            MemoryNodeType::Protocol=>"Protocol",
            MemoryNodeType::TerminalCommands=>"TerminalCommands",
            MemoryNodeType::ModelResponse=>"ModelResponse",
            MemoryNodeType::AppResponse=>"AppResponse",
            MemoryNodeType::Error=>"Error",
            MemoryNodeType::ModelError=>"ModelError",
            MemoryNodeType::Message=>"Message",
            MemoryNodeType::Signal=>"Signal",
            MemoryNodeType::Applog=>"Applog",
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
    invocation_id:Option<String>
}
impl MemoryNode {
    pub fn new(
        source: &Source,
        content: String,
        prompt_info: Option<PromptStyle>,
        node_type: MemoryNodeType,
        invocation_id:Option<String>
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
        info!("{},{:?}",content,tags);


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
            invocation_id
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
    _memory_tx: channel::Sender<MemoryNode>,
    pub _kill_switch:Arc<AtomicBool>
}

impl Memory {
    /// construct a new Memory container
    pub fn new() -> Arc<Self> {
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

        thread::spawn(move || {
            info!("Memory thread started. Memory ID: {}, Branch ID: {}", arc_memory_clone._memory_id, arc_memory_clone._branch_id);
            while let Ok(new_node) = rx_clone.recv() {
                // print!("Inserting Memory Node: {:?}", new_node);
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

                
                

                

            }
        });

        arc_memory
    }

    pub fn get_memory_tx(&self) -> Option<channel::Sender<MemoryNode>> {
        Some(self._memory_tx.clone())
    }   
    pub fn kill_memory(&self){
        // let kill_switch=self._kill_switch.load_full();
        let kill_ac=self._kill_switch.store(true,Ordering::Relaxed);

    }  
    
    pub async fn incremental_mem_nodes(&self,ref_node_id:Option<String>)-> impl Iterator<Item = MemoryNode>{
        if let Some(ref_nid)=&ref_node_id{
            let readable_mem_indx=self._memory_store.mem_indx.read().unwrap();

            let ref_indx=readable_mem_indx.get(ref_nid).cloned();
            drop(readable_mem_indx);
            match ref_indx{
                Some(ref_ix)=>{
                    self.iter_memory(Some(ref_ix+1),None).await
                }
                None=>{
                    self.iter_memory(None,None).await
                }
            }

        }
        else{
            self.iter_memory(None,None).await
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
        self._memory_tx.send(memory_node).unwrap();
    }

    pub async fn get_distinct_node_tags(&self) -> Vec<String> {
        let readable_tag_indx = self._memory_store.tags_indx.read().unwrap();
        readable_tag_indx.keys().cloned().collect()
    }

    pub async fn iter_memory(
        &self,
        start_index:Option<usize>,
        filter_tags: Option<HashSet<String>>,
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
            node.branch_id == Some(self._branch_id.clone()) 
                && match &filter_tags {
                    Some(tags) => !node.tags.is_disjoint(tags),
                    None => true,
                }
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


