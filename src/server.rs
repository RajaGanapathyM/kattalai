use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::post,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Arc};
use tokio::{sync::RwLock};
use tracing::info;
use crate::Runtime;
use crate::memory::MemoryNode;

pub type SharedRuntime = Arc<RwLock<Runtime>>;


#[derive(Serialize)]
pub struct ApiResponse<T: Serialize> {
    pub ok: bool,
    pub data: Option<T>,
    pub error: Option<String>,
}

impl<T: Serialize> ApiResponse<T> {
    fn ok(data: T) -> (StatusCode, Json<Self>) {
        (
            StatusCode::OK,
            Json(Self {
                ok: true,
                data: Some(data),
                error: None,
            }),
        )
    }

    fn err(msg: impl Into<String>) -> (StatusCode, Json<ApiResponse<()>>) {
        (
            StatusCode::BAD_REQUEST,
            Json(ApiResponse {
                ok: false,
                data: None,
                error: Some(msg.into()),
            }),
        )
    }
}

pub struct RuntimeServer;

impl RuntimeServer {

    pub async fn serve(rt: SharedRuntime, addr:String) {
        // let addr = format!("0.0.0.0:{}", port);
        let router = RuntimeServer::build_router(rt);

        let listener = match tokio::net::TcpListener::bind(&addr).await {
            Ok(l) => l,
            Err(e) => {
                eprintln!("Warning: Could not bind API port {}: {}. API server disabled.", addr, e);
                return;
            }
        };

        info!("Runtime API listening on http://{}", addr);
        println!("Runtime API listening on http://{}", addr);


        tokio::spawn(async move {
            
            axum::serve(listener, router)
                .await
                .expect("Axum server error");
        });
    }

    pub fn build_router(rt:SharedRuntime) -> Router {
        Router::new()
            // agents
            .route("/agents/list",              post(handle_get_agents_list))
            .route("/agent/deploy",             post(handle_deploy_agent))
            .route("/agent/episode-history-len",post(handle_agent_episode_history_len))
            .route("/agent/working-status",     post(handle_is_agent_working))
            .route("/agent/iter-memory",        post(handle_iter_agent_memory))
            // topics
            .route("/topic/create",             post(handle_create_topic))
            .route("/topic/history-len",        post(handle_topic_history_len))
            .route("/topic/add-agent",          post(handle_add_agent_to_topic))
            .route("/topic/remove-agent",       post(handle_remove_agent_from_topic))
            .route("/topic/iter",               post(handle_iter_topic))
            // users
            .route("/user/create",              post(handle_create_user))
            // messages
            .route("/message/insert",           post(handle_insert_message))
            .with_state(rt)
    }

}


//API handlers


//############### MESSAGE & USER API ##################
#[derive(Deserialize)]
pub struct CreateUserReq {
    pub user_name: String,
}

/// POST /user/create
async fn handle_create_user(
    State(rt): State<SharedRuntime>,
    Json(req): Json<CreateUserReq>,
) -> impl IntoResponse {
    let user_id = rt.write().await.create_user(req.user_name).await;
    ApiResponse::ok(user_id)
}


/// POST /message/insert
async fn handle_insert_message(
    State(rt): State<SharedRuntime>,
    Json(req): Json<InsertMessageReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .insert_message(&req.topic_id, &req.user_id, req.message)
        .await
    {
        Ok(msg) => ApiResponse::ok(msg).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}


//############### TOPICS API ########################


/// POST /topic/create

async fn handle_create_topic(
    State(rt): State<SharedRuntime>,
) -> impl IntoResponse {
    let topic_id = rt.write().await.create_topic_thread().await;
    ApiResponse::ok(topic_id)
}

/// POST /topic/history-len

#[derive(Deserialize)]
pub struct TopicIdReq {
    pub topic_id: String,
}

async fn handle_topic_history_len(
    State(rt): State<SharedRuntime>,
    Json(req): Json<TopicIdReq>,
) -> impl IntoResponse {
    match rt.read().await.get_topic_history_len(&req.topic_id).await {
        Ok(len) => ApiResponse::ok(len).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}



/// POST /topic/add-agent


#[derive(Deserialize)]
pub struct InsertMessageReq {
    pub topic_id: String,
    pub user_id: String,
    pub message: String,
}



#[derive(Deserialize)]
pub struct AgentTopicReq {
    pub topic_id: String,
    pub agent_id: String,
}


async fn handle_add_agent_to_topic(
    State(rt): State<SharedRuntime>,
    Json(req): Json<AgentTopicReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .add_agent_to_topic(&req.topic_id, &req.agent_id)
        .await
    {
        Ok(msg) => ApiResponse::ok(msg).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

/// POST /topic/remove-agent
async fn handle_remove_agent_from_topic(
    State(rt): State<SharedRuntime>,
    Json(req): Json<AgentTopicReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .remove_agent_from_topic(&req.topic_id, &req.agent_id)
        .await
    {
        Ok(msg) => ApiResponse::ok(msg).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}



/// POST /topic/iter
#[derive(Deserialize)]
pub struct IterTopicReq {
    pub topic_id: String,
    pub start_index: usize,
}

async fn handle_iter_topic(
    State(rt): State<SharedRuntime>,
    Json(req): Json<IterTopicReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .iter_topic(&req.topic_id, req.start_index)
        .await
    {
        Ok(iter) => {
            let nodes: Vec<serde_json::Value>= iter.map(|n|n.get_json()).collect();
            ApiResponse::ok(nodes).into_response()
        }
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}
//############### AGENTS API ########################

// POST: /agents/list --------

async fn handle_get_agents_list(
    State(rt): State<SharedRuntime>,
) -> impl IntoResponse {
    let agents = rt.read().await.get_agents_list().await;
    ApiResponse::ok(agents)
}
//------------------------------------

// POST /agent/deploy


#[derive(Deserialize)]
pub struct DeployAgentReq {
    pub agent_name: String,
}

async fn handle_deploy_agent(
    State(rt): State<SharedRuntime>,
    Json(req): Json<DeployAgentReq>,
) -> impl IntoResponse {
    let agent_id = rt.write().await.deploy_agent(req.agent_name).await;
    ApiResponse::ok(agent_id)
}



/// POST /agent/episode-history-len

#[derive(Deserialize)]
pub struct AgentEpisodeHistoryReq {
    pub topic_id: String,
    pub agent_id: String,
}

async fn handle_agent_episode_history_len(
    State(rt): State<SharedRuntime>,
    Json(req): Json<AgentEpisodeHistoryReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .get_agent_episode_history_len(&req.topic_id, &req.agent_id)
        .await
    {
        Ok(len) => ApiResponse::ok(len).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

/// POST /agent/working-status

async fn handle_is_agent_working(
    State(rt): State<SharedRuntime>,
    Json(req): Json<AgentTopicReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .is_agent_working_on_topic(&req.topic_id, &req.agent_id)
        .await
    {
        Ok(status) => ApiResponse::ok(status).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

/// POST /agent/iter-memory


#[derive(Deserialize)]
pub struct IterAgentMemoryReq {
    pub topic_id: String,
    pub agent_id: String,
    pub start_index: usize,
}

async fn handle_iter_agent_memory(
    State(rt): State<SharedRuntime>,
    Json(req): Json<IterAgentMemoryReq>,
) -> impl IntoResponse {
    match rt
        .read()
        .await
        .iter_agent_memory(&req.topic_id, &req.agent_id, req.start_index)
        .await
    {
        Ok(iter) => {
            let nodes:Vec<serde_json::Value> = iter.map(|n|n.get_json()).collect();
            ApiResponse::ok(nodes).into_response()
        }
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}