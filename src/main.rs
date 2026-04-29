
use soulengine::{Runtime,init_tracing};
use std::thread::sleep;
use tokio::time::{ Duration};
use env_logger;
#[tokio::main]
async fn main() {
    init_tracing();



    // let se_runtime=Runtime::new(Some("127.0.0.1:3166".to_string())).await;
    let se_runtime=Runtime::new(None).await;


    


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
    let mut se_write_runtime=se_runtime.write().await;
    let demo_user_id=se_write_runtime.create_user("Alice".to_string()).await;
    let topic_id=se_write_runtime.create_topic_thread().await;
    let agent_id=se_write_runtime.deploy_agent("DIA".to_string()).await;
    se_write_runtime.add_agent_to_topic(&topic_id, &agent_id).await;
    println!("Memory instance created...");
    drop(se_write_runtime);
    let se_read_runtime=se_runtime.read().await;

    
    // se_read_runtime.insert_message(&topic_id, &demo_user_id, "/morning_news_summary --run --context 'https://indianexpress.com/'".to_string()).await.unwrap();  
    // drop(se_read_runtime);  
    // sleep(Duration::from_secs(200000));
    // let se_read_runtime=se_runtime.read().await;
    // se_read_runtime.insert_message(&topic_id, &demo_user_id, "Hello, Whst is your name.".to_string()).await.unwrap();
    
    let agent_stat=se_read_runtime.is_agent_working_on_topic(&topic_id,&agent_id).await.unwrap();
    println!("Agent Status:{}",agent_stat);
    // let topic_len=se_read_runtime.get_topic_history_len(&topic_id.clone()).await.unwrap();
    println!("Main thread sleeping");

    //sleep for 3 seconds to simulate time gap between interactions
    sleep(Duration::from_secs(2));
    
    
    // se_read_runtime.insert_message(&topic_id, &demo_user_id, "Say Booo".to_string()).await;
    let topic_len=se_read_runtime.get_topic_history_len(&topic_id.clone()).await.unwrap();
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
    // drop(se_read_runtime);
    
    // let se_write_runtime=se_runtime.write().await;

    
    sleep(Duration::from_secs(3));
    // se_read_runtime.remove_agent_from_topic(&topic_id, &agent_id).await;
    

    let my_msg="you two task. first remind me after 20s to take a break and second task read and summarize my credit card statement C:/Users/RG/Downloads/CC_sample.pdf and save the summary as notes".to_string();
    // let my_msg="/morning_greeting --schedule 0 8 * * 1".to_string();
    // let my_msg="can you schedule morning_greeting protocol to run on monday morning".to_string();
    // let my_msg="can you run morning_greeting protocol after 5 secs".to_string();
    // let my_msg="check if a file called jokes.txt exists in g: drive. If it does,move it to opensource folder in the g: drive?".to_string();
    // let my_msg="can you check list of protocols scheduled and change existing protcol to run every 10 minutes".to_string();
    // let my_msg="i want every days morning news to be retrived and analysed and sumamrized for me".to_string();
    // let my_msg="My computer is slow. check what are the process running".to_string();
    // let my_msg="What is the current OS information of my computer?".to_string();
    // let my_msg="Can you open https://indianexpress.com/ and check what is the latest news?".to_string();
    // let my_msg="i want to know about Python programming. can fetch information about it?".to_string();
    // let my_msg="add the following, 23+45".to_string();
    // let my_msg="Suprise me!".to_string();
    // let my_msg="Suprise me!".to_string();
    
// let msg="".to_string();
    println!("Inserting message: {}", my_msg);

    
    se_read_runtime.insert_message(&topic_id, &demo_user_id, my_msg).await.unwrap();
    
    // drop(se_write_runtime);
    // let se_read_runtime=se_runtime.read().await;
    println!("Final Interface Memory");

    let mem_iter=se_read_runtime.iter_topic(&topic_id, 0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
    sleep(Duration::from_secs(3));

    
    println!("Final Agent Memory");
    let mem_iter=se_read_runtime.iter_agent_memory(&topic_id, &agent_id,0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
    // sleep(Duration::from_secs(3));

    // println!("Agent Memory");
    // let locked_Agent=first_agent.read().unwrap();
    // locked_Agent.print_current_episode().await;
    // drop(locked_Agent);
    // Agent::ping(&first_agent,AgentPulse::Invoke(None)).await;
    // sleep(Duration::from_secs(100));
    
    println!("Final Interface Memory");
    
    let mem_iter=se_read_runtime.iter_topic(&topic_id, 0).await.unwrap();
    for mem in mem_iter{
        println!("{}:{}",mem.get_source_name(),mem.get_content());
    }
    drop(se_read_runtime);
    sleep(Duration::from_secs(200000));
        


}
