use std::collections::HashMap;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use uuid::Uuid;

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Role {
    Agent,
    User,
    Environment,
    App,
    System,
}
impl Role {
    pub fn as_str(&self) -> &str {
        match self {
            Role::System => "system",
            Role::User => "user",
            Role::Agent => "assistant",
            Role::App => "app",
            Role::Environment => "environment",
        }
    }
}

#[derive(Clone, Debug)]
pub struct Source {
    role: Role,
    name: String,
    id: String,
    info: Option<HashMap<String, String>>,
}

impl Source {
    pub fn new(role: Role, name: String, info: Option<HashMap<String, String>>) -> Self {
        Source { role, name, id: uuid::Uuid::now_v7().to_string(), info }
    }
    pub fn get_role(&self) -> Role {
        self.role.clone()
    }
    pub fn get_name(&self) -> String {
        self.name.clone()      
    }
    pub fn get_id(&self) -> String {
        self.id.clone()      
    }
}
