use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::post,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Arc};
use tokio::sync::RwLock;
use tracing::info;

// ── Shared state ────────────────────────────────────────────────────────────

pub type SharedRuntime = Arc<RwLock<Runtime>>;

// ── Request / Response types ────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct CreateUserReq {
    pub user_name: String,
}

#[derive(Deserialize)]
pub struct DeployAgentReq {
    pub agent_name: String,
}

#[derive(Deserialize)]
pub struct TopicIdReq {
    pub topic_id: String,
}

#[derive(Deserialize)]
pub struct AgentEpisodeHistoryReq {
    pub topic_id: String,
    pub agent_id: String,
}

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

#[derive(Deserialize)]
pub struct IterTopicReq {
    pub topic_id: String,
    pub start_index: usize,
}

#[derive(Deserialize)]
pub struct IterAgentMemoryReq {
    pub topic_id: String,
    pub agent_id: String,
    pub start_index: usize,
}

// Generic API response envelope
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

// ── Handlers ────────────────────────────────────────────────────────────────

/// POST /agents/list
async fn handle_get_agents_list(
    State(rt): State<SharedRuntime>,
) -> impl IntoResponse {
    let agents = rt.read().await.get_agents_list().await;
    ApiResponse::ok(agents)
}

/// POST /topic/create
async fn handle_create_topic(
    State(rt): State<SharedRuntime>,
) -> impl IntoResponse {
    let topic_id = rt.write().await.create_topic_thread().await;
    ApiResponse::ok(topic_id)
}

/// POST /user/create
async fn handle_create_user(
    State(rt): State<SharedRuntime>,
    Json(req): Json<CreateUserReq>,
) -> impl IntoResponse {
    let user_id = rt.write().await.create_user(req.user_name).await;
    ApiResponse::ok(user_id)
}

/// POST /agent/deploy
async fn handle_deploy_agent(
    State(rt): State<SharedRuntime>,
    Json(req): Json<DeployAgentReq>,
) -> impl IntoResponse {
    let agent_id = rt.write().await.deploy_agent(req.agent_name).await;
    ApiResponse::ok(agent_id)
}

/// POST /topic/history-len
async fn handle_topic_history_len(
    State(rt): State<SharedRuntime>,
    Json(req): Json<TopicIdReq>,
) -> impl IntoResponse {
    match rt.read().await.get_topic_history_len(&req.topic_id).await {
        Ok(len) => ApiResponse::ok(len).into_response(),
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

/// POST /agent/episode-history-len
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

/// POST /topic/add-agent
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

/// POST /topic/iter
/// Returns collected memory nodes as a JSON array.
/// MemoryNode must derive Serialize for this to work.
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
            let nodes: Vec<MemoryNode> = iter.collect();
            ApiResponse::ok(nodes).into_response()
        }
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

/// POST /agent/iter-memory
/// Returns collected agent episode memory nodes as a JSON array.
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
            let nodes: Vec<MemoryNode> = iter.collect();
            ApiResponse::ok(nodes).into_response()
        }
        Err(e) => ApiResponse::<()>::err(e).into_response(),
    }
}

// ── Router builder ──────────────────────────────────────────────────────────

pub fn build_router(rt: SharedRuntime) -> Router {
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

// ── Runtime impl (new + serve) ───────────────────────────────────────────────

impl Runtime {
    pub async fn new() -> Arc<RwLock<Self>> {
        let embedder = embedder::new("./model_assets/bge-small-en-v1.5".to_string()).await;
        let app_store = AppStore::new("./apps/".to_string(), embedder.clone()).await;
        let inference_store = InferenceStore::load_configs("./configs/inference_config.toml");
        let agent_store = AgentStore::load_agents(
            "./configs/agents_config.toml",
            inference_store.clone(),
            app_store.clone(),
        );

        let rt = Arc::new(RwLock::new(Self {
            topics: HashMap::new(),
            users: HashMap::new(),
            agents: HashMap::new(),
            embedder,
            app_store,
            inference_store,
            agent_store: Arc::new(agent_store),
        }));

        // Spawn Axum server as a background task
        let rt_clone = rt.clone();
        tokio::spawn(async move {
            Self::serve(rt_clone, 3000).await;
        });

        rt
    }

    /// Starts the Axum HTTP server on `port`.
    /// Called automatically inside `new()` — no need to call manually.
    pub async fn serve(rt: SharedRuntime, port: u16) {
        let addr = format!("0.0.0.0:{}", port);
        let router = build_router(rt);

        let listener = tokio::net::TcpListener::bind(&addr)
            .await
            .expect("Failed to bind API port");

        info!("Runtime API listening on http://{}", addr);

        axum::serve(listener, router)
            .await
            .expect("Axum server error");
    }
}