use serde::Deserialize;
use std::fs;

use log::{info, warn, error, debug, trace};
use std::sync::{Arc, RwLock};
use crate::inference::{Gemini, HuggingFace, OLLAMA, SarvamConfig};
use crate::inference::{OllamaConfig,GeminiConfig,HuggingFaceConfig};
use crate::inference::inference_api_trait;
use crate::terminal::Terminal;
use crate::tool::{App,AppType};
use crate::{model, source};

use crate::inference;

#[derive(Debug, Deserialize, Clone)]
pub struct OllamaConfigLoader {
    pub chat_api_url: String,
    pub generate_api_url: String,
    pub temperature: f32,
}

#[derive(Debug, Deserialize, Clone)]
pub struct GeminiConfigLoader {
    pub api_key: String,
    pub temperature: f32,
}

#[derive(Debug, Deserialize, Clone)]
pub struct HuggingFaceConfigLoader {
    pub api_key: String,
    pub max_new_tokens: u32,
    pub temperature: f32,
}

#[derive(Debug, Deserialize, Clone)]
pub struct SarvamConfigLoader {
    pub api_key: String,
    pub max_new_tokens: u32,
    pub temperature: f32,
    pub reasoning_effort:String
}

#[derive(Debug, Deserialize, Clone)]
pub struct InferenceConfig {
    pub ollama_config: Vec<OllamaConfigLoader>,
    pub gemini_config: Vec<GeminiConfigLoader>,
    pub huggingface_config: Vec<HuggingFaceConfigLoader>,
    pub sarvam_config: Vec<SarvamConfigLoader>,
}

pub struct InferenceStore{
    config:InferenceConfig
}

impl InferenceStore {
    pub fn load_configs(path: &str) -> Arc<Self> {
        let content = fs::read_to_string(path).unwrap();
        let config: InferenceConfig = toml::from_str(&content).unwrap();
        Arc::new(Self{config:config})
    }
    pub fn get_model(&self,inference_provider:String,model_id:&String)-> Arc<dyn inference_api_trait + Send + Sync>{
        if inference_provider=="ollama"{
            if self.config.ollama_config.len()>0{
                let ollama_config=&self.config.ollama_config[0];
                OllamaConfig::new(
                    ollama_config.chat_api_url.clone(), 
                    ollama_config.generate_api_url.clone(),
                    vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
                    vec![source::Role::User, source::Role::Agent].into_iter().collect(),
                    false,
                    Some(ollama_config.temperature),
                    None,   
                ).get_model(model_id.clone())
            }
            else{
                panic!("Ollama Config not found");
            }

        }
        else if inference_provider=="gemini"{
            if self.config.gemini_config.len()>0{
                let gemini_config=&self.config.gemini_config[0];
                GeminiConfig::new(
                    gemini_config.api_key.clone(), 
                    vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
                    vec![source::Role::User, source::Role::Agent].into_iter().collect(),
                    false,
                    Some(gemini_config.temperature),
                    None,   
                ).get_model(model_id.clone())
            }
            else{
                panic!("Gemini Config not found");
            }
        }
        else if inference_provider=="huggingface"{
            if self.config.huggingface_config.len()>0{
                let huggingface_config=&self.config.huggingface_config[0];
                HuggingFaceConfig::new(
                    huggingface_config.api_key.clone(), 
                    vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
                    vec![source::Role::User, source::Role::Agent].into_iter().collect(),
                    false,
                    Some(huggingface_config.temperature),
                    None,   
                    Some(huggingface_config.max_new_tokens.clone())
                ).get_model(model_id.clone())
            }
            else{
                panic!("HuggingFace Config not found");
            }
        }
        else if inference_provider=="sarvam"{
            if self.config.sarvam_config.len()>0{
                let sarvam_config=&self.config.sarvam_config[0];
                SarvamConfig::new(
                    sarvam_config.api_key.clone(), 
                    vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
                    vec![source::Role::User, source::Role::Agent].into_iter().collect(),
                    false,
                    Some(sarvam_config.temperature),
                    None,   
                    Some(sarvam_config.max_new_tokens.clone()),
                    Some(sarvam_config.reasoning_effort.clone())
                ).get_model(model_id.clone())
            }
            else{
                panic!("Sarvam Config not found");
            }
        }
        else{            
            panic!("Inference Config not found");
        }

    }
}