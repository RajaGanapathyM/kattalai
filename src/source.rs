use std::collections::HashMap;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
use uuid::Uuid;
use std::str::FromStr;

use log::{info, warn, error, debug, trace};
use serde_json::Value;
use crate::database::{DB,DBTable};
use std::sync::{Arc,RwLock,OnceLock};
use tokio::sync::OnceCell;
pub static GLOBAL_SOURCE_DB: OnceCell<Arc<DBTable>> = OnceCell::const_new();

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
    pub fn resolve_source_async(source:impl std::future::Future<Output = Source>)->Source{
        tokio::task::block_in_place(|| {
             let tokio_crt=tokio::runtime::Handle::current();
             tokio_crt.block_on(async {
                source.await
             })
        })

    }
    pub fn export_as_json(&self) -> Value {
        serde_json::json!({
            "role": self.role.as_str(),
            "name": self.name,
            "source_id": self.id,
        })
    }
    pub fn get_schema() -> Value {
        serde_json::json!({
            "role": "TEXT",
            "name": "TEXT",
            "source_id": "TEXT",
        })
    }
    pub async fn init_source_db()->Arc<DB>{
        Arc::new(DB::new("sources".into(), 20).await.unwrap())
    }
    pub async fn new(role: Role, name: String, info: Option<HashMap<String, String>>) -> Self {
        let source_table=GLOBAL_SOURCE_DB.get_or_init(||async  {
            let source_db=Source::init_source_db().await;
            DBTable::new("sources".to_string(), Source::get_schema(), source_db.pool.clone()).await
        }).await;
        
        let new_source = Source { role, name, id: uuid::Uuid::now_v7().to_string(), info };
        if let Err(e) = source_table.insert(vec![new_source.export_as_json()]).await {
            error!("Failed to insert source into database {}",e);
        }
        new_source

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
