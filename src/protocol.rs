use crate::agent::{Agent, PromptStyle,agent_model_config};
use crate::app::App;
use tokio::runtime::Handle;
use futures::executor::block_on;
use crate::memory::{Memory,MemoryNode,MemoryNodeType};
use crate::protocol;

use std::io::{BufRead, BufReader, Write,BufWriter};
use std::fs::{OpenOptions, create_dir_all};
use std::path::Path;
use crate::inference::{inference_api_trait};
use crate::terminal::Terminal;
use arc_swap::cache;
use crate::appstore::AppStore;
use crate::config::InferenceConfig;
use crate::source::{Source,Role};
use uuid::Uuid;
use std::fmt::format;
use std::sync::Arc;
use std::fs;
use crate::config::InferenceStore;
use std::hash::Hash;
use std::collections::HashMap;
use crate::appstore::find_matching_toml_dirs;
use regex::Regex;

#[derive(Debug, Clone, PartialEq,serde::Serialize, serde::Deserialize)]
pub struct ProtocolStep{
    id: i32,
    label: Option<String>,
    app_command: Option<String>,
    prompt: Option<String>, 
    
}

pub struct Protocol{
    protocol_card:Source,
    protocol_id:String,
    protocol_name: String,
    protocol_description:Option<String>,
    protocol_handle_name: String,
    protocol_result:String,
    trigger_prompt:Option<String>,
    step: Vec<ProtocolStep>,   
    interface_memory:Arc<Memory>,
    reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
    terminal:Arc<Terminal>,
    protocol_md:String
}

impl Protocol{
    pub async fn new(
        protocol_config:ProtocolConfig,
        protocol_md_path:String,
        reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
        interface_memory:Arc<Memory>,
        app_store:Arc<AppStore>
    )-> Self{
        
        let pcard=Source::new(Role::App,format!("{}ProtocolRunner",protocol_config.protocol_name.clone()),None);

        let terminal=Arc::new(Terminal::new(interface_memory.get_memory_tx()));
        for app_handle_name in protocol_config.apps_used.iter(){
            let app=app_store.clone_app(app_handle_name.clone());
            terminal.launch_app(app).await;
        }
        Self{
            protocol_id: Uuid::now_v7().to_string(),
            protocol_card: pcard,
            protocol_name: protocol_config.protocol_name.clone(),
            protocol_description: protocol_config.protocol_description.clone(),
            protocol_handle_name: protocol_config.protocol_handle_name.clone(),
            protocol_result: protocol_config.protocol_result.clone(),
            trigger_prompt: protocol_config.trigger_prompt.clone(),
            step: protocol_config.step.clone(),
            reasoning_model,
            terminal:terminal,
            interface_memory,
            protocol_md:std::fs::read_to_string(protocol_md_path.clone()).unwrap()
        }
    }

    fn get_sys_prompt(&self,step_id:i32)->String{
        include_str!("../prompts/AGENT_PROTOCOL_PROMPT.md").replace("__protocol_md__", &self.protocol_md).replace("__current_step_id__", &step_id.to_string())
    }
    pub async fn run(&self){
        let agent_card=Source::new(Role::App, format!("{}ProtocolRunner",self.protocol_handle_name), None);
        let invocation_id=Uuid::now_v7().to_string();
        println!("Running protocol: {}", self.protocol_name);
        let mut current_step_id=-1;
        loop{
            println!("Invoking reasoning model for protocol: {}", self.protocol_name);
            let model_resp=self.reasoning_model.chat(
                self.interface_memory.clone(), 
                self.get_sys_prompt(current_step_id), 
                Some(invocation_id.clone()),
                Some(&agent_card)

            ).await; 
            println!("Model response: {}", model_resp);

            let parsed_resp=ProtocolRespParser::parse_model_response(model_resp);  
            if parsed_resp.is_ok(){
                let protocol_response=parsed_resp.unwrap();
                println!("Protocol response: {:?}", protocol_response);
                let new_content=format!("Protocol Runner Update:\n Protocol Name: {}\nDecision: {:?}\nReason: {:?}\nMessage: {:?}", self.protocol_name, protocol_response.decision, protocol_response.reason, protocol_response.message);
                let protocol_reason_msg=MemoryNode::new(&self.protocol_card ,new_content, Some(PromptStyle::PROTOCOL), MemoryNodeType::ProtocolLog,Some(invocation_id.clone()),Some(&agent_card));
                self.interface_memory.insert(protocol_reason_msg).await;
                
                match protocol_response.decision{
                    ProtocolDecision::NextStep=>{
                        let step_opt=protocol_response.next_step;
                        let mut wait_sec=5;
                        if let Some(step)=step_opt{
                            println!("Executing step: {}", step.id);
                            current_step_id=step.id;

                            if let Some(app_command) = &step.app_command{
                                println!("Running app command: {}", app_command);
                                self.terminal.execute_command(app_command.clone(),self.interface_memory._memory_id.clone(),invocation_id.clone()).await;
                                wait_sec=15;
                            }
                            if let Some(prompt) = &step.prompt{
                                if prompt.trim().is_empty(){
                                    println!("Prompt for step {} is empty, skipping prompt insertion.", step.id);
                                }
                                else {
                                    println!("Running prompt: {}", prompt);
                                    let output_memory_node=MemoryNode::new(&self.protocol_card ,prompt.clone(), None, MemoryNodeType::ProtocolPrompt,Some(invocation_id.clone()),None);
                                    self.interface_memory.insert(output_memory_node).await;
                                    wait_sec=30;
                                }
                            }

                        }
                        println!("Model decided to move to next step. Moving to step id: {} | Wait Duration: {}s", current_step_id, wait_sec);
                        tokio::time::sleep(std::time::Duration::from_secs(wait_sec)).await;
                    },
                    ProtocolDecision::Wait=>{
                        println!("Model decided to wait. Reason: {}", protocol_response.reason);
                        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                    },
                    ProtocolDecision::ProtocolComplete=>{
                        let output_memory_node=MemoryNode::new(&self.protocol_card ,format!("Protocol {} execution complete!", self.protocol_name), None, MemoryNodeType::ProtocolPrompt,Some(invocation_id.clone()),Some(&agent_card));
                        self.interface_memory.insert(output_memory_node).await;
                        break
                    },
                    ProtocolDecision::ProtocolError=>{
                        let output_memory_node=MemoryNode::new(&self.protocol_card ,format!("Protocol Error: Protocol_Name: {}  Error Message: {:?}", self.protocol_name, protocol_response.message), None, MemoryNodeType::ProtocolLog,Some(invocation_id.clone()),Some(&agent_card));
                        self.interface_memory.insert(output_memory_node).await;
                        break
                    }
                }
            }
            else {
                println!("Failed to parse model response for protocol {}: {:?}", self.protocol_name, parsed_resp.err().unwrap());
               
            }

        }
    }
}


#[derive(Debug, Clone, PartialEq,serde::Serialize, serde::Deserialize)]
pub enum ProtocolDecision{
    NextStep,
    Wait,
    ProtocolComplete,
    ProtocolError
}


#[derive(Debug, Clone, PartialEq,serde::Serialize, serde::Deserialize)]
pub struct ProtocolResponse {
    pub decision: ProtocolDecision,
    pub reason: String,
    pub message: Option<String>,
    pub next_step: Option<ProtocolStep>
}
#[derive(Debug)]
pub enum ProtocolParseError {
    RegexError(String),
    JsonError(String),
    
}

struct ProtocolRespParser;
impl ProtocolRespParser{
    pub fn parse_model_response(model_resp:String)->Result<ProtocolResponse, ProtocolParseError>{
        if model_resp.trim().is_empty(){
            return Err(ProtocolParseError::JsonError("Model response is empty".to_string()));
        }
        let parsed_resp=ProtocolRespParser::extract_json_block(&model_resp);
        parsed_resp
    }
    fn extract_json_block(resp:&String) -> Result<ProtocolResponse, ProtocolParseError>{
        let json_block_pattern=r"```\s*\n?json\s*\n?([\s\S]*?)```";
        let re= Regex::new(json_block_pattern).map_err(|e: regex::Error| ProtocolParseError::RegexError(e.to_string()))?;
        
        if let Some(caps) = re.captures(resp){
            if let Some(json_str) = caps.get(1){
                let json_block=json_str.as_str();
                let protocol_response: ProtocolResponse = serde_json::from_str(json_block).map_err(|e| ProtocolParseError::JsonError(e.to_string()))?;
                Ok(protocol_response)
            }else{
                Err(ProtocolParseError::JsonError("No JSON block found in the response".to_string()))
            }
        }else{
            Err(ProtocolParseError::JsonError("No JSON block found in the response".to_string())) 
        }
    }
}



///////////Protocol Store
#[derive(Debug, Clone, PartialEq,serde::Serialize, serde::Deserialize)]
pub struct ProtocolConfig{
    protocol_name: String,
    protocol_description:Option<String>,
    protocol_handle_name: String,
    trigger_prompt:Option<String>,
    protocol_result:String,
    apps_used: Vec<String>,
    step: Vec<ProtocolStep>
}


#[derive(Debug, Clone, serde::Deserialize)]
pub struct ProtocolMasterConfig{
    reasoning_model:agent_model_config,
    nlp_model:agent_model_config
}

pub struct ProtocolStore{
    protocol_stor_card:Source,
    protocol_dir_path: String,
    protocols: HashMap<String, ProtocolConfig>,
    protocols_path: HashMap<String, String>,
    protocol_master_config: ProtocolMasterConfig,
    app_store: Arc<AppStore>,
    inference_store: Arc<InferenceStore>
}

impl ProtocolStore{
    pub fn new(protocol_dir_path: String,app_store:Arc<AppStore>,inference_store:Arc<InferenceStore>)-> Arc<Self>{
        let protocol_master_config_str=std::fs::read_to_string("./configs/protocol_config.toml".clone()).unwrap();
        let protocol_master_config: ProtocolMasterConfig = toml::from_str(&protocol_master_config_str).unwrap();
        let mut pstore=Self{
            protocol_stor_card: Source::new(Role::App, "ProtocolStore".to_string(), None),
            protocol_dir_path,
            protocols: HashMap::new(),
            protocols_path: HashMap::new(),
            protocol_master_config,
            app_store,
            inference_store
        };
        pstore.load_protocols();

        Arc::new(pstore)
    }

    pub async fn handle_unknown_cmd(&self, cmd: &str,interface_memory: Arc<Memory>) {
        interface_memory.insert(MemoryNode::new(
            &self.protocol_stor_card,
            format!("Invalid Protocol command: {}", cmd),
            None,
            MemoryNodeType::ProtocolPrompt,
            Some(Uuid::now_v7().to_string()),
            None
        )).await;
    }
    pub fn get_protocols_book(&self)->String{
        let mut book=String::new();
        book.push_str(&format!("| Protocol | Description | How to initiate | When to trigger | Protocol ExpectedResult |"));
        for (protocol_handle, protocol_config) in self.protocols.iter(){
            book.push_str(&format!("| {} | {} | {} | {} | {} |\n", protocol_config.protocol_name, protocol_config.protocol_description.clone().unwrap_or("No description".to_string()), protocol_config.protocol_handle_name, protocol_config.trigger_prompt.clone().unwrap_or("No trigger prompt".to_string()), protocol_config.protocol_result));
        }
        book
    }

    pub fn schedule_protocol(&self,
        handle_name: &str,
        schedule_string: &str,
        memory_id: String,
    ) -> Result<(), String> {

        let schedule_entry = format!("{}|{}|{}\n", memory_id, schedule_string, handle_name);

        if schedule_entry.trim().is_empty() {
            return Err("Schedule entry is empty".to_string());
        }

        println!("📌 Entry length: {}", schedule_entry.len());
        println!("📌 Entry content: {:?}", schedule_entry);

        let dir_path = Path::new("./configs");
        if let Err(e) = create_dir_all(dir_path) {
            return Err(format!("Failed to create directory: {}", e));
        }

        let file_path = dir_path.join("protocol_schedules.txt");

        println!("Target file path: {:?}", file_path);

        match std::fs::canonicalize(&file_path) {
            Ok(path) => println!("Canonical path: {:?}", path),
            Err(_) => println!("⚠️ File not yet created, will create new"),
        }

        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&file_path);

        let file = match file {
            Ok(f) => {
                println!("File opened successfully");
                f
            }
            Err(e) => {
                return Err(format!("Failed to open file: {}", e));
            }
        };

        let mut writer = BufWriter::new(file);

        if let Err(e) = writer.write_all(schedule_entry.as_bytes()) {
            return Err(format!("Write failed: {}", e));
        } else {
            println!("Write successful");
        }

        if let Err(e) = writer.flush() {
            return Err(format!("Flush failed: {}", e));
        } else {
            println!("Flush successful");
        }

        drop(writer);

        match std::fs::read_to_string(&file_path) {
            Ok(content) => {
                if !content.contains(&schedule_entry.trim()) {
                    println!("Entry not found after write (possible overwrite elsewhere)");
                } else {
                    println!("Entry verified in file");
                }
            }
            Err(e) => {
                println!("Could not verify file content: {}", e);
            }
        }

        Ok(())
    }

    // pub async fn show_schedules(&self,interface_memory:Arc<Memory>)-> Vec<String>{
    //     let file_path = "./configs/protocol_schedules.txt";
    //     if let Ok(file) = fs::File::open(file_path) {
    //         let reader = BufReader::new(file);
    //         let schedules=reader.lines().filter_map(|line| line.ok()).collect::<Vec<String>>();
    //         let content=format!("Current Protocol Schedules:\n{}", schedules.join("\n"));

    //         interface_memory.insert(MemoryNode::new(&self.protocol_stor_card ,content, None, MemoryNodeType::ProtocolPrompt,Some(Uuid::now_v7().to_string()),None)).await;
            

    //     }

    //     self.protocols.keys().cloned().collect()
    // }
    pub async fn trigger_protocol(&self, protocol_handle: String,interface_memory:Arc<Memory>){
        let handle = Handle::current();
        if let Some(protocol_config) = self.protocols.get(&protocol_handle){
            let protocol_path = self.protocols_path.get(&protocol_handle).unwrap().clone();
            let reasoning_model = self.inference_store.get_model(self.protocol_master_config.reasoning_model.inference_provider.clone(),&self.protocol_master_config.reasoning_model.model_id.clone());
            let interface_memory_clone=interface_memory.clone();
            let app_store_clone=self.app_store.clone();
            let protocol_config_clone=protocol_config.clone();



            tokio::spawn(async move{
                let protocol_inst=Protocol::new(
                    protocol_config_clone,
                    protocol_path,
                    reasoning_model,
                    interface_memory_clone,
                    app_store_clone
                ).await;
            
                protocol_inst.run().await;
            });

            interface_memory.insert(MemoryNode::new(&self.protocol_stor_card,format!("Launched protocol: {}", protocol_config.protocol_name), None,MemoryNodeType::Applog,Some(Uuid::now_v7().to_string()),Some(&self.protocol_stor_card))).await;

        }
        else{
            interface_memory.insert(MemoryNode::new(&self.protocol_stor_card,format!("Protocol with handle {} not found", protocol_handle), None,MemoryNodeType::Applog,Some(Uuid::now_v7().to_string()),Some(&self.protocol_stor_card))).await;
        }

    
    }


    pub fn load_protocols(&mut self){
        let mut matches: Vec<String> = Vec::new();
        find_protocol_tomls(&self.protocol_dir_path, &mut matches);
        println!("Found protocol configs: {:?}", matches);
        for protocol_path in matches{
            let protocol_md_read=std::fs::read_to_string(protocol_path.clone());
            if let Ok(protocol_md)=protocol_md_read{
                let protocolconfig=toml::from_str::<ProtocolConfig>(&protocol_md).unwrap();
                println!("Found protocol config: {:?}", protocolconfig);
                self.protocols_path.insert(protocolconfig.protocol_handle_name.clone(), protocol_path);
                self.protocols.insert(protocolconfig.protocol_handle_name.clone(), protocolconfig);
            }
            else{
                println!("Failed to read protocol file: {}", protocol_path);
            }
        }
            // Here you would read the TOML file, parse it, and create Protocol instances to store in the protocols HashMap

    }
}



pub fn find_protocol_tomls(root: &str, matches: &mut Vec<String>) {
    if let Ok(entries) = fs::read_dir(root) {

        println!("entries in {}: {:?}", root, entries );
        for entry in entries.flatten() {
            let path = entry.path();
            println!("Checking path: {:?}", path);

            // Skip hidden directories
            if path.is_dir() {
                if let Some(dir_name) = path.file_name().and_then(|n| n.to_str()) {
                    if dir_name.starts_with('.') {
                        continue;
                    }
                }

                // Recurse into subdirectory
                if let Some(sub_path) = path.to_str() {
                    find_protocol_tomls(sub_path, matches);
                }
            } else {
                // Check if file is .toml
                if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                    if ext == "toml" {
                        matches.push(path.to_string_lossy().to_string());
                    }
                }
            }
        }
    }
    else{
        println!("Failed to read directory: {}", root);
    }
}