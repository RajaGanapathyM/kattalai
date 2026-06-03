use std::collections::HashMap;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use uuid::Uuid;
use std::str::FromStr;

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Role {
    Agent,
    User,
    Environment,
    App,
    System,
    Runtime,
    Protocol,
}
impl Role {
    pub fn as_str(&self) -> &str {
        match self {
            Role::System => "system",
            Role::User => "user",
            Role::Agent => "assistant",
            Role::App => "app",
            Role::Environment => "environment",
            Role::Runtime => "runtime",
            Role::Protocol => "protocol",
        }
    }
}

impl FromStr for Role {
    type Err = ();
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "system" => Ok(Role::System),
            "user" => Ok(Role::User),
            "agent" | "assistant" => Ok(Role::Agent),
            "app" => Ok(Role::App),
            "environment" => Ok(Role::Environment),
            "runtime" => Ok(Role::Runtime),
            "protocol" => Ok(Role::Protocol),
            _ => Err(()),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
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
