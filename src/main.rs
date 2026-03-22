use soulengine::Runtime;
use std::thread::sleep;
use tokio::time::{ Duration};

#[tokio::main]
async fn main() {

    let mut se_runtime=Runtime::new().await;


    


    // // --- 2. Embed a batch of documents ---
    // let documents = vec![
    //     "Rust is a systems programming language focused on safety and performance.".to_string(),
    //     "Python is a high-level language great for scripting and data science.".to_string(),
    // ];


    // println!("Embedding {} documents...", documents.len());
    // let embeddings=embedder.get_embeddings(documents.clone()).await.unwrap();

    // println!("Embedding shape: {} vectors of dimension {}\n", embeddings.len(), embeddings[0].len());

    // let app= App::new(
    //     "DemoApp".to_string(),
    //     "./demo.py".to_string(),
    //     HashMap::new(),
    //     "python".to_string(),
    //     "./demo.py".to_string(),
    //     "demo_app".to_string(),
    //     AppType::REPL,
    //     "call app to show demo".to_string()

    // );

    // app_store.add_app(
    //     "G:\\bitBucketRepo\\bRowSe\\soul_engine\\apps\\notes_app\\notes_app.toml".to_string()
    // );

    // app_store.add_app(
    //     "G:\\bitBucketRepo\\bRowSe\\soul_engine\\apps\\clock_app\\clock_app.toml".to_string()
    // );

    // app_store.add_app(
    //     "G:\\bitBucketRepo\\bRowSe\\soul_engine\\apps\\calculator_app\\calculator_app.toml".to_string()
    // );

    // app_store.add_app(
    //     "G:\\bitBucketRepo\\bRowSe\\soul_engine\\apps\\grep_app\\grep_app.toml".to_string()
    // );



        
    // let embedder=embedder::new("./model_assets/bge-small-en-v1.5".to_string()).await;

    // let app_store=AppStore::new("./apps/".to_string(),embedder).await;

    // let inference_store=InferenceStore::load_configs("./configs/inference_config.toml");

    // let agent_store=AgentStore::load_agents("./configs/agents_config.toml", inference_store.clone(), app_store.clone());



    // let mut terminal=Terminal::new();
    // terminal.launch_app(app).await;
    // sleep(Duration::from_secs(5));
    // terminal.execute_command("&demo_app 1\n".to_string()).await;
    // sleep(Duration::from_secs(1));

    
    // terminal.execute_command("&demo_app 2".to_string()).await;
    // sleep(Duration::from_secs(5));

    
    // terminal.execute_command("&demo_app 3\n".to_string()).await;


    // build a memory instance asynchronously
    let demo_user_id=se_runtime.create_user("Alice".to_string()).await;
    let topic_id=se_runtime.create_topic_thread().await;
    let agent_id=se_runtime.deploy_agent("DIA".to_string()).await;
    println!("Memory instance created...");

    se_runtime.insert_message(&topic_id, &demo_user_id, "Hello, Whst is your name.".to_string()).await.unwrap();
    
    let agent_stat=se_runtime.is_agent_working_on_topic(&topic_id,&agent_id).await.unwrap();
    println!("Agent Status:{}",agent_stat);
    // let topic_len=se_runtime.get_topic_history_len(&topic_id.clone()).await.unwrap();
    println!("Main thread sleeping");

    //sleep for 3 seconds to simulate time gap between interactions
    sleep(Duration::from_secs(2));
    
    
    se_runtime.insert_message(&topic_id, &demo_user_id, "Say Booo".to_string()).await;
    let topic_len=se_runtime.get_topic_history_len(&topic_id.clone()).await.unwrap();
    println!("Memory sequence length: {}", topic_len);
    
    // /
    // / build a model instance qwen3:4b llama3.2:3b deepseek-r1:1.5b phi3:mini phi4:mini
    // let ollama = OllamaConfig::new(
    //     // "qwen3:4b".to_string(), 
    //     "http://localhost:11434/api/chat".to_string(), 
    //     "http://localhost:11434/api/generate".to_string(),
    //     vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
    //     vec![source::Role::User, source::Role::Agent].into_iter().collect(),
    //     false,
    //     Some(0.1),
    //     None,   
    // );

    
    // let gemini = GeminiConfig::new(21211222221``
    // // "gemini-2.5-flash".to_string(), // Use a Gemini model instead of Qwen
    // std::env::var("GEMINI_API_KEY").expect("GEMINI_API_KEY environment variable not set"), // Replaces the two localhost URLs
    // vec![source::Role::User, source::Role::Agent,source::Role::App].into_iter().collect(),
    // vec![source::Role::User, source::Role::Agent].into_iter().collect(),
    // false,      // stream_response
    // Some(0.1),  // temperature
    // None,       // top_p
    // );
    // // print!("Model Response: {}", ollama.generate("Sing a song".to_string()).await);
    // let huggingface = HuggingFaceConfig::new(
    //     // "meta-llama/Llama-3.3-70B-Instruct".to_string(),
    //     std::env::var("HF_API_KEY").expect("HF_API_KEY environment variable not set"),
    //     vec![source::Role::User, source::Role::Agent, source::Role::App].into_iter().collect(),
    //     vec![source::Role::User, source::Role::Agent].into_iter().collect(),
    //     false,      // stream_response
    //     Some(0.1),  // temperature
    //     None,       // top_p
    //     Some(8192), // max_new_tokens
    // );
    

    // let qwen_reasoning_model=ollama.get_model("qwen3:4b".to_string());
    // let qwen_nl_nodel=ollama.get_model("qwen3:0.6b".to_string());


    // let mut first_agent=Agent::new(
    //     "DIA".to_string(), 
    //     "To assist user with their queries".to_string(), 
    //     "You are Ai assistant".to_string(), 
    //     HashMap::new(),
    //     qwen_reasoning_model.clone() ,
    //     qwen_nl_nodel.clone() ,
    //     None,
    //     arced_appstore.clone()
    // );
    // Agent::ping(&first_agent,AgentPulse::AttachApp(arced_appstore.clone_app("clock_app".to_string()))).await;
    // // Agent::ping(&first_agent,AgentPulse::AttachApp(clock_app)).await;
    // Agent::ping(&first_agent,AgentPulse::AttachApp(arced_appstore.clone_app("calculator_app".to_string()))).await;
    
    

    // Agent::ping(&first_agent,AgentPulse::AddMemory(MemoryNode::new(&demo_user, "Call demo app and update me once demo app execution completed".to_string(), None, MemoryNodeType::Thought),None)).await;
    se_runtime.add_agent_to_topic(&topic_id, &agent_id).await;
    sleep(Duration::from_secs(3));
    se_runtime.remove_agent_from_topic(&topic_id, &agent_id).await;
    

    let my_msg="wait for 5 sec and get stock price of HDFCBANK.NS and analyse".to_string();

    
    se_runtime.insert_message(&topic_id, &demo_user_id, my_msg).await.unwrap();
    
    println!("Final Interface Memory");

    let mem_iter=se_runtime.iter_topic(&topic_id, 0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
    sleep(Duration::from_secs(3));

    
    println!("Final Agent Memory");
    let mem_iter=se_runtime.iter_agent_memory(&topic_id, &agent_id,0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
    sleep(Duration::from_secs(3));

    // println!("Agent Memory");
    // let locked_Agent=first_agent.read().unwrap();
    // locked_Agent.print_current_episode().await;
    // drop(locked_Agent);
    // Agent::ping(&first_agent,AgentPulse::Invoke(None)).await;
    // sleep(Duration::from_secs(100));
    sleep(Duration::from_secs(200000));
    println!("Final Interface Memory");
    
    let mem_iter=se_runtime.iter_topic(&topic_id, 0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
        


}
