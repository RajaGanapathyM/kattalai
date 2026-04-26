use serde_json::map::Iter;
use tokio::process::{Command, Child};
use tokio::sync::Mutex;
use std::mem;
use log::{info, warn, error, debug, trace};
use async_trait::async_trait;
use std::thread::sleep;
use std::process::Stdio;
use std::sync::Arc;
use std::collections::HashMap;
// use std::thread::sleep;
use std::fs;
use tokio::time::{ Duration};
use crate::agent::{AgentPulse, episode};
use crate::app;
use crate::{
    memory::{Memory, MemoryNode, MemoryNodeType},
    source::{Role, Source},
};
use tokio::io::AsyncWriteExt;
use regex::Regex;
use serde::Deserialize;


#[derive(Debug, Deserialize,Clone)]
pub struct CmdSignature {
    pub command:String,
    pub consumes:Vec<String>,
    pub produces:Vec<String>,
    pub action:String
}

#[derive(Debug, Deserialize,Clone)]
pub struct AppConfig {
    app_name:String,
    app_path:String,
    app_start_command:String,
    app_start_args:String,
    app_handle_name:String,
    app_usage_guideline:String,
    app_launch_mode:String,
    app_command_signatures:Vec<CmdSignature>
}
impl AppConfig {
    pub fn get_cmd_signatures(&self)->Vec<CmdSignature>{
        self.app_command_signatures.clone()
    }
    pub fn get_app_handle_name(&self)->String{
        self.app_handle_name.clone()
    }
    pub fn get_guidelines(&self)->String{
        self.app_usage_guideline.clone()
    }
    
}


#[derive(Debug,Clone)]
pub enum AppType{
    REPL,
    ONE_SHOT,
}


#[derive(Debug)]
pub struct App {
    pub app_card: Source,
    app_path: String,
    app_start_command: String,
    app_start_args: String,
    app_process: Arc<Mutex<Option<Child>>>,
    pub app_handle_name:String,
    app_type: AppType,
    _mem_tx: Mutex<Option<crossbeam::channel::Sender<AgentPulse>>>,
    app_usage_guideline:String,
    app_command_signatures:Vec<CmdSignature>
}

impl App {
    pub fn new(
        app_toml_path:String,
        app_info: HashMap<String, String>,
    ) -> Self {

            let app_config_file = fs::read_to_string(app_toml_path).unwrap();
            // info!("{}",app_config_file);
            let appconfig: AppConfig = toml::from_str(&app_config_file).unwrap();

            let mut app_type=AppType::ONE_SHOT;
            if appconfig.app_launch_mode=="REPL"{
                app_type=AppType::REPL;
            }
            else if appconfig.app_launch_mode=="ONE_SHOT"{                
                app_type=AppType::ONE_SHOT;
            }
            else{
                info!("Unknown Lauch mode given for app:{}. Allowed are REPL or ONE_SHOT.Defaulting to ONE_SHOT Model",appconfig.app_name);
            }

            Self {
                app_card: Source::new(Role::App, appconfig.app_name, Some(app_info)),
                app_path:appconfig.app_path,
                app_start_command:appconfig.app_start_command,
                app_start_args:appconfig.app_start_args,
                app_process: Arc::new(Mutex::new(None)),
                app_handle_name:appconfig.app_handle_name,
                app_type,
                _mem_tx: Mutex::new(None),
                app_usage_guideline:appconfig.app_usage_guideline,
                app_command_signatures:appconfig.app_command_signatures 

            }
        }
        pub fn get_cmd_signatures(&self)->std::slice::Iter<'_,CmdSignature>{
            self.app_command_signatures.iter()
        }
        fn _launch_kernel(&self,cmd_args:String)->Child{
            info!("Kernel launched");
            let app_child = Command::new(&self.app_start_command)
            .args(cmd_args.split_whitespace())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("Failed to start the application");

            app_child

        }
        
        pub fn get_guidelines(&self)->String{
            self.app_usage_guideline.clone()
        }
        pub async fn launch(&self) {
            info!("Starting app: {}", self.app_card.get_name());

            match &self.app_type {
                AppType::REPL => {
                    let app_child=self._launch_kernel(self.app_start_args.clone());

                    let mut guard = self.app_process.lock().await;
                    *guard = Some(app_child);
                },
                AppType::ONE_SHOT => info!("Launching app in ONE_SHOT mode..."),
            }
            
        }
        
        fn parse_resp(app_card:&Source,resp:String,invocation_id:Option<String>)->Option<AgentPulse>{

            match &AppResponseParser::parse(&resp){
                Ok(parsed)=>{
                    // sleep(Duration::from_secs(5));
                    let new_mem_node=MemoryNode::new(app_card, format!("> APP Returns : APP NAME:{}|App Status:{}|{}",app_card.get_name(),parsed.command.clone(),parsed.message.clone()), None, MemoryNodeType::AppResponse,invocation_id,None);

                    info!("[App]{:?}",new_mem_node.get_content());
                    if parsed.command=="APP_EXECUTION_SUCCESS" || parsed.command=="APP_EXECUTION_ERROR" || parsed.command=="APP_INVOKE"{
                        Some(AgentPulse::AddMemoryAndInvoke(new_mem_node,Some(parsed.episode_id.clone())))
                    }
                    else{
                        Some(AgentPulse::AddMemory(new_mem_node,Some(parsed.episode_id.clone())))

                    }

                    
                },
                Err(e)=>{
                    error!("APPLOG:{:?}",e);
                    None
                }
            }

        }
        pub async fn attach(&self, mem_tx_channel: crossbeam::channel::Sender<AgentPulse>) {
            info!("Attaching output listener to app: {}", self.app_card.get_name());
            
            match &self.app_type {
                
                AppType::ONE_SHOT => {
                    info!("Attaching to ONE_SHOT app...");
                    let mut _writable_mem_Tx=self._mem_tx.lock().await;
                    *_writable_mem_Tx = Some(mem_tx_channel);
                
                    
                },
                AppType::REPL => {
                    info!("Attaching to REPL app...");
                    let mut guard = self.app_process.lock().await;

                    if let Some(child) = guard.as_mut() {
                        if let Some(stdout) = child.stdout.take() {
                            let mem_tx = mem_tx_channel.clone();

                            let app_card = self.app_card.clone(); // IMPORTANT

                            tokio::spawn(async move {
                                use tokio::io::{AsyncBufReadExt, BufReader};

                                let reader = BufReader::new(stdout);
                                let mut lines = reader.lines();

                                while let Ok(Some(line)) = lines.next_line().await {
                                    let parsed_resp=App::parse_resp(&app_card,line,None);

                                    if let Some(msg_node)=parsed_resp{
                                        // println!("sending message from app to agent: {:?}", msg_node);
                                        let _ = mem_tx.send(msg_node);

                                    }

                                    
                                }
                            });
                        }
                    }
                }
            }
        }
        pub async fn execute(&self, command_str:String,invocation_id:String){
            info!("Running command {} in app: {}", command_str,self.app_card.get_name());

            match &self.app_type {
                AppType::ONE_SHOT=>{
                    let combined_args=format!("{} {}",self.app_start_args,command_str);
                    info!("Combined Args {}",combined_args);
                    let mut app_child=self._launch_kernel(combined_args);
                    let stdout=app_child.stdout.take().expect("App child is none");
                    let app_card=self.app_card.clone();
                    let mem_tx_guard=self._mem_tx.lock().await;
                    let mem_tx_clone=match &*mem_tx_guard {
                        Some(mem_tx)=>{
                            Some(mem_tx.clone())
                        },
                        None=>{None}
                    };
                                    
                    tokio::spawn(async move {
                        use tokio::io::{AsyncBufReadExt, BufReader};

                        let reader = BufReader::new(stdout);
                        let mut lines = reader.lines();
                        

                        while let Ok(Some(line)) = lines.next_line().await {
                            match &mem_tx_clone{
                                Some(mem_tx_channel) => {
                                    let parsed_resp=App::parse_resp(&app_card,line,Some(invocation_id.clone()));

                                    if let Some(msg_node)=parsed_resp{
                                        let _ = mem_tx_channel.send(msg_node);

                                    }
                                }
                                None => {info!("Output of App:{}", line);}
                            }
                        }
                    });
                }
                AppType::REPL=>{
                    let mut guard = self.app_process.lock().await;
                    // info!("App process lock acquired for command execution.");
                    if let Some(child) = guard.as_mut() {
                        match(child.try_wait()){
                            Ok(Some(status)) => {
                                info!("App {} - exited with status: {}", self.app_card.get_name(), status);
                                return;
                            },
                            Ok(None) => {
                                if let Some(stdin) =&mut child.stdin {
                                    info!("Writing {} to stdin",command_str);
                                    if let Err(e) = stdin.write_all(format!("{}\n",command_str).as_bytes()).await {
                                        info!("Failed to write to app {} stdin: {}", self.app_card.get_name(), e);
                                    }
                                    stdin.flush().await;
                                }
                                else {
                                    info!("App {} stdin is not available.", self.app_card.get_name());
                                    
                                }
                            },
                            Err(e) => {
                                info!("App {} Error checking app process status: {}", self.app_card.get_name(), e);
                                return;
                            }
                            _ => {
                                info!("Unexpected error checking app process status.");
                                return;
                            }

                        }
                    }
                    else {
                        info!("App process is not running.");
                        return;
                    }
                }
            }
        }    
    }


#[derive(Debug)]
pub enum AppParseError {
    RegexError(String),
    ParseError(String),
    IgnoreMessage(String),
    AppError(String),
    UnknownResponse(String)
}

#[derive(Debug)]
struct ParsedResp{
    episode_id:String,
    invocation_id:String,
    message:String,
    command:String
}
pub struct AppResponseParser;

#[derive(Debug, Deserialize)]
struct SpillEnvelope {
    #[serde(rename = "__spilled__")]
    spilled: bool,
    file: String,
}

impl AppResponseParser  {
    pub fn parse(resp:&String) -> Result<ParsedResp, AppParseError>{
        if resp.trim().len()==0{
            Err(AppParseError::IgnoreMessage("Response is empty.".to_string()))
        }
        else if resp.trim().contains("[#APP_ERROR>"){
            Err(AppParseError::AppError(resp.clone()))
        }
        else if resp.starts_with("[#"){
            Self::parse_appresp(resp)
        }
        else{
            Err(AppParseError::UnknownResponse(resp.clone()))
        }
    }

    fn resolve_spill(resp:&String)->String{
        
        info!("Resolving spilled content from file: {:?}",resp);
        let spillResp:SpillEnvelope= serde_json::from_str(resp).unwrap();
        

        if spillResp.spilled{
            let spilled_content=fs::read_to_string(&spillResp.file).map_err(|e| format!("{:?}",e)).unwrap();

            if let Err(e)=fs::remove_file(&spillResp.file){
                error!("Failed to remove spill file: {:?}. Error: {:?}",spillResp.file,e);
            }


            return spilled_content;
        }
        else{
            return resp.clone();
        }
    }

    fn parse_appresp(resp:&String) -> Result<ParsedResp, AppParseError>{
        let resp_pattern=r"^\[#(?P<command>[A-Z_]+)>episode_id:(?P<episode_id>[^|]+)\|invocation_id:(?P<invocation_id>[^\]]+)\](?P<message>.*)$";
;
        let re= Regex::new(resp_pattern).map_err(|e: regex::Error| AppParseError::RegexError(e.to_string()))?;

        let respmatch= re.captures(resp);
        
        if let Some(cap)=respmatch{
            let command=cap.name("command").unwrap().as_str().to_string();
            let episode_id=cap.name("episode_id").unwrap().as_str().to_string();
            let invocation_id=cap.name("invocation_id").unwrap().as_str().to_string();
            let mut msg=cap.name("message").unwrap().as_str().to_string();

            if msg.contains("__spilled__"){
                msg=AppResponseParser::resolve_spill(&msg);
            }

            Ok(ParsedResp{episode_id,invocation_id,message:msg,command})

        }
        else{
            Err(AppParseError::UnknownResponse(resp.clone()))
        }

    }

}
