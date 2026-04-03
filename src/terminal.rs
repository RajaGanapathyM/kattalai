use serde::{Deserialize, Serialize};
use app::App;
use std::collections::HashMap;
use crate::memory::Memory;
use std::sync::{Arc};
use tokio::sync::RwLock;
use crate::app;
use crate::agent::AgentPulse;
use log::{info, warn, error, debug, trace};
use async_trait::async_trait;

pub struct Terminal{
    env_vars: Vec<(String, String)>,
    app_hooks:Arc<RwLock<HashMap<String, Arc<App>>>>,
}

impl Terminal{
    pub fn new() -> Self {
        Self {
            env_vars: Vec::new(),
            app_hooks:Arc::new(RwLock::new(HashMap::new()))
        }
    }

    pub async fn launch_app(&self, app: App, memory_rx:Option<crossbeam::channel::Sender<AgentPulse>>) {
        let app_handle_name = app.app_handle_name.clone();
        let app_hook_loc=self.app_hooks.read().await;
        let has_app=!app_hook_loc.contains_key(&format!("&{}", app_handle_name)).clone();
        drop(app_hook_loc);

        if has_app{
            app.launch().await;
            self.app_hooks.write().await.insert(format!("&{}", app_handle_name), Arc::new(app));
            info!("App Launched: {}",app_handle_name);
            if let Some(mem_rx)=memory_rx{
                self.attach_memory(mem_rx).await;
            }
        }
        else{
            info!("App Alread Exist: {}",app_handle_name);
        }
    }
    
    pub async fn attach_memory(&self, mem_tx: crossbeam::channel::Sender<AgentPulse>) {

        for (app_handle_name, app) in self.app_hooks.read().await.iter(){
            info!("Attached app:{}",app_handle_name);
            app.attach(mem_tx.clone()).await;
        }
    }

    pub async fn get_app_guidebook(&self) -> String {
        let mut app_guide_book = String::new();
        let mut app_list = String::new();
        app_list.push_str("List of currently running/available Apps:\n");

        for (index, (app_name, app)) in self.app_hooks.read().await.iter().enumerate() {
            app_list.push_str(&format!("{}. {}\n", index + 1, app_name));
            app_guide_book.push_str(&format!(
                "App #{}: {}\n Command to invoke:{}\n Usage guideline:{}\n\n",
                index + 1,
                app_name,
                app_name,
                app.get_guidelines()
            ));
        }

        format!("{}\nApps Guidebook:\n{}", app_list, app_guide_book)
    }

    pub async fn validate_app_commands(&self,commands:&Vec<String>)->Vec<String>{
        let mut error_ls:Vec<String>=Vec::new();
        for cmd in commands{
            let command_args=cmd.split_whitespace().collect::<Vec<&str>>();

            let app_handle_name=command_args[0].to_string();

            if app_handle_name.starts_with("&"){
                if !self.app_hooks.read().await.contains_key(&app_handle_name) {
                    error_ls.push(format!("App with handle name '{}' not found for command execution.", app_handle_name));
                }
            }
            else{
                error_ls.push(format!("Command '{}' not recognized as an app command.", cmd));
            }
        }
        error_ls
    }

    pub async fn execute_multi_commands(&self,commands:&Vec<String>,episode_id:String,invocation_id:String){
        for command in commands{
            info!("Executing command:{}",command);
            self.execute_command(command.clone(),episode_id.clone(),invocation_id.clone()).await;
        }
    }
    pub async fn execute_command(&self, command: String,episode_id:String,invocation_id:String) {

        let command_args=command.split_whitespace().collect::<Vec<&str>>();

        let app_handle_name=command_args[0].to_string();
        let mut app:Option<Arc<App>>=None;
        if app_handle_name.starts_with("&"){
            let app_hook_readable= self.app_hooks.read().await;
            
            if app_hook_readable.contains_key(&app_handle_name) {
                app = {
                    let app_hook_readable = self.app_hooks.read().await;
                    app_hook_readable.get(&app_handle_name).cloned()
                };
            }

        }
        else{
            info!("Command '{}' not recognized as an app command.", command);
            return;
        }
        
        if let Some(app) = &app{
            app.clone().execute(format!("--episode_id {} --invocation_id {} {}",episode_id.clone(),invocation_id.clone(),command_args[1..].join(" ")),invocation_id.clone()).await;
        }
    
        else {
            info!("App with handle name '{}' not found for command execution.", app_handle_name);
        }
    }

    
}   