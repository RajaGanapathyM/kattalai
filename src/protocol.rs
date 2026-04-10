use crate::agent::Agent;
use crate::memory::{Memory,MemoryNode,MemoryNodeType};
use crate::terminal::Terminal;
use arc_swap::cache;
use crate::source::{Source,Role};
use uuid::Uuid;
use crate::inference::{ inference_api_trait,invoke_type};
use std::sync::Arc;

use regex::Regex;
pub struct protocol_step{
    id: u32,
    label: Option<String>,
    app_command: Option<String>,
    prompt: Option<String>, 
    
}

pub struct protocol{
    protocol_card:Source,
    protocol_id:String,
    protocol_name: String,
    protocol_description:Option<String>,
    protocol_handle_name: String,
    trigger_prompt:Option<String>,
    steps: Vec<protocol_step>,   
    memory:Arc<Memory>,
    reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
    terminal:Terminal,
    protocol_md:String
}

impl protocol{
    pub fn new(
        protocol_name: String,
        protocol_description:Option<String>,
        protocol_handle_name: String,
        trigger_prompt:Option<String>,
        steps: Vec<protocol_step>,
        protocol_md:String,
        reasoning_model:Arc<dyn inference_api_trait + Send + Sync>,
        memory:Arc<Memory>,
        terminal:Terminal
    )-> Self{
        
        let pcard=Source::new(Role::App,format!("{}ProtocolRunner",protocol_name.clone()),None),
        Self{
            protocol_id: Uuid::now_v7().to_string(),
            protocol_card: pcard,
            protocol_name,
            protocol_description,
            protocol_handle_name,
            trigger_prompt,
            steps,
            memory,
            reasoning_model,
            terminal,
            protocol_md
        }
    }

    fn get_sys_prompt(&self)->String{
        format!(
            include_str!("../prompts/AGENT_PROTOCOL_PROMPT.md"),
            protocol_md=self.protocol_md.clone()
        )
        
    }
    pub async fn run(&self){
        let invocation_id=Uuid::now_v7().to_string();
        println!("Running protocol: {}", self.protocol_name);
        loop{
            let model_resp=self.reasoning_model.chat(
                self.memory.clone(), 
                self.get_sys_prompt(), 
                Some(invocation_id.clone())
            ).await; 
            println!("Model response: {}", model_resp);

            let parsed_resp=ProtocolRespParser::parse_model_response(model_resp);  
            if parsed_resp.is_ok(){
                let protocol_response=parsed_resp.unwrap();

                
                
                println!("Protocol response: {:?}", protocol_response);
                
                let protocol_reason_msg=MemoryNode::new(&self.protocol_card ,format!("Protocol Step Reason: {}\nMessage:{}", protocol_response.reason.clone(),protocol_response.message.clone() ), None, MemoryNodeType::AppResponse,Some(invocation_id.clone()));
                self.memory.insert(protocol_reason_msg).await;
                
                match protocol_response.decision{
                    ProtocolDecision::NextStep=>{
                        let step=protocol_response.next_step;
                        
                        println!("Executing step: {}", step.id);

                        if let Some(app_command) = &step.app_command{
                            println!("Running app command: {}", app_command);
                            self.terminal.execute_command(app_command.clone(),self.memory._memory_id.clone(),invocation_id.clone()).await;
                        }
                        if let Some(prompt) = &step.prompt{
                            println!("Running prompt: {}", prompt);
                            let output_memory_node=MemoryNode::new(&self.protocol_card ,prompt.clone(), None, MemoryNodeType::Message,Some(invocation_id.clone()));
                            self.memory.insert(output_memory_node).await;
                        }
                    },
                    ProtocolDecision::Wait=>{
                        println!("Model decided to wait. Reason: {}", protocol_response.reason);
                        tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                    },
                    ProtocolDecision::ProtocolComplete=>{
                        println!("Protocol complete! Message: {}", protocol_response.message);
                        break;
                    },
                    ProtocolDecision::ProtocolError=>{
                        println!("Protocol error! Reason: {}. Message: {}", protocol_response.reason, protocol_response.message);
                        break;
                    }
                }
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
pub struct ProtocolStep{
    id: u32,
    label: Option<String>,
    app_command: Option<String>,
    prompt: Option<String>,
}


#[derive(Debug, Clone, PartialEq,serde::Serialize, serde::Deserialize)]
pub struct ProtocolResponse {
    pub decision: ProtocolDecision,
    pub reason: String,
    pub message: String,
    pub next_step: ProtocolStep
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
