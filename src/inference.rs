use std::alloc::System;
use std::{collections::HashSet, vec};
use reqwest::Client;
use serde_json::{json, Value};
use crate::memory::{Memory, MemoryNode,MemoryNodeType};
use crate::source::{Role, Source};
use std::sync::Arc;
use async_trait::async_trait;
use uuid::Uuid;
pub enum invoke_type {
    Chat,
    Generate,
}

use log::{info, warn, error, debug, trace};
#[async_trait]
pub trait inference_api_trait {
    async fn generate(&self, prompt: String) -> String;
    async fn chat(&self,memory: Arc<Memory>,system_prompt:String,invocation_id:Option<String>) -> String;
    
    async fn invoke(&self,api_url: &str, payload: Value, invoke_type: invoke_type) -> String {
        let client = Client::new();
        let response = match client
            .post(api_url)
            .json(&payload)
            .send()
            .await {
                Ok(resp) => match resp.text().await {
                    Ok(text) => text,
                    Err(e) => return format!("[ERROR] Failed to read response: {}", e),
                },
                Err(e) => return format!("[ERROR] Inference request failed: {}. Check if the provider is running.", e),
            };
        self.parse_response(response, invoke_type).await
    }
    async fn parse_response(&self, response: String, invoke_type: invoke_type) -> String {
            let parsed: Value = serde_json::from_str(&response).expect("Invalid JSON");
            
            match invoke_type {
                invoke_type::Chat => {
                    parsed["message"]["content"]
                        .as_str()
                        .expect("Response Parsing Failed")
                        .to_string()
                },
                invoke_type::Generate => {
                    // info!("{:?}",parsed);
                    parsed["response"]
                        .as_str()
                        .expect("Response Parsing Failed")
                        .to_string()
                }
            }

            // MemoryNode::new("assistant".to_string(), content)
        }


    
    
    async fn filter_messages(&self, memory: Arc<Memory>,invocation_id:Option<String>,allowed_roles: &HashSet<Role>,non_tool_roles: &HashSet<Role>,) -> Vec<Value>{
        memory.iter_memory(None,None).await
            .filter(|node| { 
                let error_current_invocation_flag=if node.get_node_type()==MemoryNodeType::ModelError{
                    match &invocation_id{
                        Some(in_id)=>{
                            if let Some(nivc_id)=&node.get_invocation_id(){
                                nivc_id==in_id
                            }
                            else{
                                true
                            }
                        },
                        None=>{true}
                    }
                }
                else{
                    true
                };

                node.is_allowed(allowed_roles) && error_current_invocation_flag
            
            
            })
            .map(|node| node.get_payload(non_tool_roles))
            .collect::<Vec<Value>>()
        }
    
    async fn request_payload_builder(&self, message_history: &mut Vec<Value>,system_prompt:String)->Value;
    async fn _chat_invoke(&self,chat_api_url:&String, memory: Arc<Memory>,system_prompt:String,invocation_id:Option<String>,allowed_roles: &HashSet<Role>,non_tool_roles: &HashSet<Role>,) -> String{
        let mut message_history=self.filter_messages(memory,invocation_id,allowed_roles,non_tool_roles).await;
        let payload= self.request_payload_builder(&mut message_history,system_prompt).await;
        // print!("Request Payload: {}", serde_json::to_string_pretty(&payload).unwrap());

        self.invoke(chat_api_url, payload, invoke_type::Chat).await
    
    }
}


//OLAMA Config


pub struct OllamaConfig {
    pub chat_api_url: String,
    pub generate_api_url: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,

}

impl OllamaConfig {
    pub fn new(
        chat_api_url: String,
        generate_api_url: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
    ) -> Self {
        Self {
            chat_api_url,
            generate_api_url,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
        }
    }

    pub fn get_model(&self,model_id:String)->Arc<OLLAMA>{
        OLLAMA::new(
            model_id,
            self.chat_api_url.clone(),
            self.generate_api_url.clone(),
            self.allowed_roles.clone(),
            self.non_tool_roles.clone(),
            self.stream_response.clone(),
            self.temperature.clone(),
            self.top_p.clone(),
        )
    }
}


pub struct OLLAMA {
    pub model_id: String,
    pub chat_api_url: String,
    pub generate_api_url: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,

}

impl OLLAMA {
    pub fn new(
        model_id: String,
        chat_api_url: String,
        generate_api_url: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
    ) -> Arc<Self> {
        Arc::new(Self {
            model_id,
            chat_api_url,
            generate_api_url,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
        })
    }
}

#[async_trait]
impl inference_api_trait for OLLAMA {
    

    async fn chat(&self,memory: Arc<Memory>,system_prompt:String,invocation_id:Option<String>) -> String{
        self._chat_invoke(
            &self.chat_api_url, 
            memory,
            system_prompt,
            invocation_id,
            &self.allowed_roles,
            &self.non_tool_roles
        ).await
    }

    async fn generate(&self,prompt: String) -> String {
        let payload = serde_json::json!({
            "model": self.model_id.clone(),
            "prompt": prompt,
            "stream": self.stream_response.clone(),
            "options": {
                "temperature": self.temperature.unwrap_or(1.0),
                "top_p": self.top_p.unwrap_or(1.0),
            }
        });
        self.invoke(&self.generate_api_url, payload, invoke_type::Generate).await
    }

    async fn request_payload_builder(&self, message_history: &mut Vec<Value>,system_prompt:String) -> Value {

        let system_msg = serde_json::json!({
            "role": "system",
            "content": system_prompt.clone(),
        });
        message_history.insert(0, system_msg);
        

        let payload=serde_json::json!({
            "model": self.model_id.clone(), 
            "messages": message_history,
            "stream": self.stream_response.clone(),
            "options": {
                "temperature": self.temperature.unwrap_or(1.0),
                "top_p": self.top_p.unwrap_or(1.0),
            }
        });
        payload
    }

    
}



//GEMINI INTEGRATIONS


pub struct GeminiConfig {
    pub api_key: String, // Replaces static URLs; Gemini handles endpoints dynamically
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
}

impl GeminiConfig {
    pub fn new(
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
    ) -> Self {
        Self {
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
        }
    }

    pub fn get_model(&self,model_id:String)->Arc<Gemini>{
        Gemini::new(
            model_id,
            self.api_key.clone(),
            self.allowed_roles.clone(),
            self.non_tool_roles.clone(),
            self.stream_response.clone(),
            self.temperature.clone(),
            self.top_p.clone(),
        )

    }
}


pub struct Gemini {
    pub model_id: String,
    pub api_key: String, // Replaces static URLs; Gemini handles endpoints dynamically
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
}

impl Gemini {
    pub fn new(
        model_id: String,
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
    ) -> Arc<Self> {
        Arc::new(Self {
            model_id,
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
        })
    }

    /// Helper to dynamically build the correct endpoint based on streaming preferences
    pub fn get_api_url(&self) -> String {
        let method = if self.stream_response {
            "streamGenerateContent"
        } else {
            "generateContent"
        };
        format!(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:{}?key={}",
            self.model_id, method, self.api_key
        )
    }
}

#[async_trait]
impl inference_api_trait for Gemini {
    
    async fn chat(&self, memory: Arc<Memory>, system_prompt: String, invocation_id: Option<String>) -> String {
        // Pass the dynamically generated URL into your invoke handler
        self._chat_invoke(
            &self.get_api_url(), 
            memory,
            system_prompt,
            invocation_id,
            &self.allowed_roles,
            &self.non_tool_roles
        ).await
    }

    async fn generate(&self, prompt: String) -> String {
        // Gemini expects a `contents` array with a `parts` object
        let payload = serde_json::json!({
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": self.temperature.unwrap_or(1.0),
                "topP": self.top_p.unwrap_or(1.0),
            }
        });
        
        self.invoke(&self.get_api_url(), payload, invoke_type::Generate).await
    }

    async fn request_payload_builder(&self, message_history: &mut Vec<Value>, system_prompt: String) -> Value {
        
        // Map standard {role: "...", content: "..."} to Gemini's {role: "...", parts: [{text: "..."}]}
        let gemini_messages: Vec<Value> = message_history.iter().map(|msg| {
            // Gemini uses 'model' instead of 'assistant'
            let role = match msg["role"].as_str().unwrap_or("user") {
                "assistant" => "model",
                "system" => "user", // Prevent system roles inside the contents array
                "user" => "user", // Prevent system roles inside the contents array
                // "tool" => "function", // Prevent system roles inside the contents array
                // "app" => "function", // Prevent system roles inside the contents array
                other => "",
            };
            
            let content = msg["content"].as_str().unwrap_or("");
            
            serde_json::json!({
                "role": role,
                "parts": [{"text": content}]
            })
        }).collect();

        let mut payload = serde_json::json!({
            "contents": gemini_messages,
            "generationConfig": {
                "temperature": self.temperature.unwrap_or(1.0),
                "topP": self.top_p.unwrap_or(1.0), // Note: Gemini API expects capital 'P'
            }
        });

        // Unlike Ollama, Gemini places the system prompt in a dedicated 
        // `systemInstruction` root field, NOT as an injected message in the history.
        if !system_prompt.is_empty() {
            payload.as_object_mut().unwrap().insert(
                "systemInstruction".to_string(),
                serde_json::json!({
                    "parts": [{"text": system_prompt}]
                })
            );
        }

        payload
    }

    async fn parse_response(&self, response: String, invoke_type: invoke_type) -> String {
        let parsed: Value = serde_json::from_str(&response).expect("Invalid JSON");

        // Gemini nests the response text deep within the candidates array.
        // The path is: candidates[0].content.parts[0].text
        // print!("PARSED:{:?}",parsed);
        let content = parsed["candidates"][0]["content"]["parts"][0]["text"]
            .as_str()
            .expect("Response Parsing Failed: Could not find text in Gemini response. Check for safety blocks or API errors.")
            .to_string();

        match invoke_type {
            invoke_type::Chat => content,
            invoke_type::Generate => content,
        }

        // MemoryNode::new("assistant".to_string(), content)
    }
}


//Hugging Face integrations

pub struct HuggingFaceConfig {
    pub api_key: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
    pub max_new_tokens: Option<u32>, // HF-specific: controls generation length
}

impl HuggingFaceConfig {
    pub fn new(
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
        max_new_tokens: Option<u32>,
    ) -> Self {
        Self {
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
            max_new_tokens,
        }
    }
    pub fn get_model(&self,model_id:String)->Arc<HuggingFace>{
        HuggingFace::new(
            model_id,
            self.api_key.clone(),
            self.allowed_roles.clone(),
            self.non_tool_roles.clone(),
            self.stream_response.clone(),
            self.temperature.clone(),
            self.top_p.clone(),
            self.max_new_tokens.clone(),
            
        )
    }
}


pub struct HuggingFace {
    pub model_id: String,
    pub api_key: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
    pub max_new_tokens: Option<u32>, // HF-specific: controls generation length
}

impl HuggingFace {
    pub fn new(
        model_id: String,
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
        max_new_tokens: Option<u32>,
    ) -> Arc<Self> {
        Arc::new(Self {
            model_id,
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
            max_new_tokens,
        })
    }

    pub fn get_api_url(&self) -> String {
        "https://router.huggingface.co/v1/chat/completions".to_string()
        // model_id goes in the request payload as "model", NOT in the URL
    }

    pub fn get_generate_url(&self) -> String {
        "https://router.huggingface.co/v1/chat/completions".to_string()
        // same endpoint for everything now
    }
    

    /// Authorization header value expected by all HF Inference API calls.
    pub fn auth_header(&self) -> String {
        format!("Bearer {}", self.api_key)
    }
}

#[async_trait]
impl inference_api_trait for HuggingFace {

    async fn chat(
        &self,
        memory: Arc<Memory>,
        system_prompt: String,
        invocation_id: Option<String>,
    ) -> String {
        self._chat_invoke(
            &self.get_api_url(),
            memory,
            system_prompt,
            invocation_id,
            &self.allowed_roles,
            &self.non_tool_roles,
        )
        .await
    }

    async fn generate(&self, prompt: String) -> String {
        // HF's raw inference endpoint expects `inputs` at the top level,
        // with generation knobs nested under `parameters`.
        let payload = serde_json::json!({
            "inputs": prompt,
            "parameters": {
                "temperature": self.temperature.unwrap_or(1.0),
                "top_p": self.top_p.unwrap_or(1.0),
                "max_new_tokens": self.max_new_tokens.unwrap_or(512),
                "return_full_text": false  // return only the generated part, not the prompt
            }
        });

        self.invoke(&self.get_generate_url(), payload, invoke_type::Generate).await
    }

    async fn request_payload_builder(
        &self,
        message_history: &mut Vec<Value>,
        system_prompt: String,
    ) -> Value {
        // HF's OpenAI-compat endpoint uses the same {role, content} shape as OpenAI,
        // so no role remapping is needed — unlike Gemini's "model"/"user" convention.
        let mut messages: Vec<Value> = Vec::new();

        // HF honours a leading system message inside the `messages` array,
        // unlike Gemini which uses a dedicated `systemInstruction` root field.
        if !system_prompt.is_empty() {
            messages.push(serde_json::json!({
                "role": "system",
                "content": system_prompt
            }));
        }

        // Append the conversation history, filtering out any bare "system" entries
        // that were already injected above to avoid duplication.
        for msg in message_history.iter() {
            let role = msg["role"].as_str().unwrap_or("user");
            if role == "system" {
                continue; // already handled above
            }
            if role == "tool" {
                
                messages.push(serde_json::json!({
                    "role": role,
                    "tool_call_id":Uuid::now_v7().to_string(),
                    "content": msg["content"].as_str().unwrap_or("")
                }));

                continue; // already handled above
            }
            messages.push(serde_json::json!({
                "role": role,
                "content": msg["content"].as_str().unwrap_or("")
            }));
        }

        serde_json::json!({
            "model": self.model_id,   // required by the compat endpoint
            "messages": messages,
            "temperature": self.temperature.unwrap_or(1.0),
            "top_p": self.top_p.unwrap_or(1.0),
            "max_tokens": self.max_new_tokens.unwrap_or(512),
            "stream": self.stream_response
        })
    }

    async fn parse_response(&self, response: String, invoke_type: invoke_type) -> String {
        let parsed: Value = match serde_json::from_str(&response){
            Ok(v) => v,
            Err(e) => {
                panic!(
                    "Invalid JSON:\n  Error: {}\n  Raw bytes: {:?}\n  Raw string: '{}'",
                    e,
                    response.as_bytes(),
                    response
                );
            }
        };
        // print!("Parsed Response Structure: {:#?}", parsed);
        match invoke_type {
            // OpenAI-compat chat response: choices[0].message.content
            invoke_type::Chat => {
                parsed["choices"][0]["message"]["content"]
                    .as_str()
                    .expect(
                        "Response Parsing Failed: could not find content in HuggingFace \
                         chat response. Check model availability or API quota.",
                    )
                    .to_string()
            }

            // Raw inference response: array of objects, first item has `generated_text`
            // e.g. [{"generated_text": "..."}]
            invoke_type::Generate => {
                parsed[0]["generated_text"]
                    .as_str()
                    .expect(
                        "Response Parsing Failed: could not find generated_text in \
                         HuggingFace inference response.",
                    )
                    .to_string()
            }
        }
    }
    
    async fn invoke(&self, api_url: &str, payload: Value, invoke_type: invoke_type) -> String {
        let client = Client::new();

        let response = client
            .post(api_url)
            .header("Authorization", self.auth_header()) // HF requires Bearer token
            .header("Content-Type", "application/json")
            .json(&payload)
            .send()
            .await
            .expect("Inference Request failed")
            .text()
            .await
            .expect("Failed to read response");

        // print!("Raw Response: {}", response);
        self.parse_response(response, invoke_type).await
    }
}


//Sarvam Integrations


pub struct SarvamConfig {
    pub api_key: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
    pub max_tokens: Option<u32>,
    /// Controls the tradeoff between speed and reasoning quality. 
    /// Valid values: "low", "medium", "high"
    pub reasoning_effort: Option<String>, 
}

impl SarvamConfig {
    pub fn new(
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
        max_tokens: Option<u32>,
        reasoning_effort: Option<String>,
    ) -> Self {
        Self {
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
            max_tokens,
            reasoning_effort,
        }
    }

    pub fn get_model(&self, model_id: String) -> Arc<SarvamAI> {
        SarvamAI::new(
            model_id,
            self.api_key.clone(),
            self.allowed_roles.clone(),
            self.non_tool_roles.clone(),
            self.stream_response,
            self.temperature,
            self.top_p,
            self.max_tokens,
            self.reasoning_effort.clone(),
        )
    }
}

// --- Implementation Struct ---

pub struct SarvamAI {
    pub model_id: String,
    pub api_key: String,
    pub allowed_roles: HashSet<Role>,
    pub non_tool_roles: HashSet<Role>,
    pub stream_response: bool,
    pub temperature: Option<f32>,
    pub top_p: Option<f32>,
    pub max_tokens: Option<u32>,
    pub reasoning_effort: Option<String>,
}

impl SarvamAI {
    pub fn new(
        model_id: String,
        api_key: String,
        allowed_roles: HashSet<Role>,
        non_tool_roles: HashSet<Role>,
        stream_response: bool,
        temperature: Option<f32>,
        top_p: Option<f32>,
        max_tokens: Option<u32>,
        reasoning_effort: Option<String>,
    ) -> Arc<Self> {
        Arc::new(Self {
            model_id,
            api_key,
            allowed_roles,
            non_tool_roles,
            stream_response,
            temperature,
            top_p,
            max_tokens,
            reasoning_effort,
        })
    }

    /// Primary endpoint for Chat and Text Generation
    pub fn get_api_url(&self) -> String {
        "https://api.sarvam.ai/v1/chat/completions".to_string()
    }

    /// Sarvam uses a custom subscription key header
    pub fn auth_header_key(&self) -> &str {
        "api-subscription-key"
    }
}

#[async_trait]
impl inference_api_trait for SarvamAI {

    async fn chat(
        &self,
        memory: Arc<Memory>,
        system_prompt: String,
        invocation_id: Option<String>,
    ) -> String {
        self._chat_invoke(
            &self.get_api_url(),
            memory,
            system_prompt,
            invocation_id,
            &self.allowed_roles,
            &self.non_tool_roles,
        )
        .await
    }

    async fn generate(&self, prompt: String) -> String {
        // Sarvam recommends using Chat Completions for all text tasks.
        // We wrap the prompt in a single-turn user message.
        let mut history = vec![json!({
            "role": "user",
            "content": prompt
        })];

        let payload = self.request_payload_builder(&mut history, "".to_string()).await;

        self.invoke(&self.get_api_url(), payload, invoke_type::Chat).await
    }

    async fn request_payload_builder(
        &self,
        message_history: &mut Vec<Value>,
        system_prompt: String,
    ) -> Value {
        let mut messages: Vec<Value> = Vec::new();

        // Include System Prompt if provided
        if !system_prompt.is_empty() {
            messages.push(json!({
                "role": "system",
                "content": system_prompt
            }));
        }

        // Standardize History
        for msg in message_history.iter() {
            let role = msg["role"].as_str().unwrap_or("user");
            if role == "system" { continue; } // Skip nested system prompts
            
            let mut msg_item = json!({
                "role": role,
                "content": msg["content"].as_str().unwrap_or(""),
                "name": msg["name"].as_str().unwrap_or("")

            });

            if role == "tool" {
                msg_item["role"] = serde_json::json!("assistant".to_string());
                // msg_item["tool_call_id"] = serde_json::json!(Uuid::now_v7().to_string());
            }
            
            messages.push(msg_item);
        }

        let mut payload = json!({
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature.unwrap_or(0.2), // Sarvam Doc Default
            "top_p": self.top_p.unwrap_or(1.0),
            "max_tokens": self.max_tokens.unwrap_or(512),
            "stream": self.stream_response
        });
        // print!("Request Payload: {}", serde_json::to_string_pretty(&payload).unwrap());
        // Inject reasoning controls for models like Sarvam-105b
        if let Some(ref effort) = self.reasoning_effort {
            payload["reasoning_effort"] = json!(effort);
        }

        payload
    }

    async fn parse_response(&self, response: String, _invoke_type: invoke_type) -> String {
        let parsed: Value = serde_json::from_str(&response).expect("Failed to parse Sarvam response");

        let message = &parsed["choices"][0]["message"];
        
        // Prioritize final content, fallback to reasoning_content if it's a thinking model
        message["content"]
            .as_str()
            .or_else(|| message["reasoning_content"].as_str())
            .unwrap_or("")
            .to_string()
    }

    async fn invoke(&self, api_url: &str, payload: Value, invoke_type: invoke_type) -> String {
        let client = Client::new();

        let response = client
            .post(api_url)
            .header(self.auth_header_key(), &self.api_key)
            .header("Content-Type", "application/json")
            .json(&payload)
            .send()
            .await
            .expect("Sarvam API Request failed")
            .text()
            .await
            .expect("Failed to read response body");

        self.parse_response(response, invoke_type).await
    }
}