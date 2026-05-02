use tokio::process::{Command, Child};
use tokio::sync::Mutex;
use std::hash::Hash;
use std::mem;
use itertools::Itertools;
use petgraph::graph::DiGraph;
use async_trait::async_trait;
use std::thread::sleep;
use petgraph::{Graph, Direction};
use petgraph::graph::NodeIndex;
use petgraph::dot::{Dot, Config};
use std::process::Stdio;
use std::sync::{Arc, RwLock};

use std::collections::VecDeque;
use std::collections::{HashMap, HashSet};
// use std::thread::sleep;
use std::fs;
use tokio::time::{ Duration};
use crate::embeddings::{embedder};
use crate::agent::{AgentPulse, episode};
use crate::app::{self, App,CmdSignature,AppType};
use crate::source;
use crate::{
    memory::{Memory, MemoryNode, MemoryNodeType},
    source::{Role, Source},
};
use crate::app::{AppConfig};
use tokio::io::AsyncWriteExt;
use regex::Regex;
use serde::{Deserialize, de};
use strsim::jaro_winkler;

use petgraph::visit::Bfs;

use std::sync::{ OnceLock};
pub static GLOBAL_APP_STORE: OnceLock<Arc<AppStore>> = OnceLock::new();
use log::{info, warn, error, debug, trace};

pub fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();

    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }

    dot / (norm_a * norm_b)
}

#[derive(Debug, Clone)]
pub struct AppInit{
    app_toml_path:String,
    app_info: HashMap<String, String>,
    app_config:AppConfig
}
impl AppInit{
    
    pub fn get_cmd_signatures(&self)->Vec<CmdSignature>{
        let cmd_sig=self.app_config.get_cmd_signatures();
        cmd_sig
    }
    pub fn get_guidelines(&self)->String{
        self.app_config.get_guidelines()
    }
}
pub struct AppStore{
    apps_dir:String,
    apps:RwLock<HashMap<String,AppInit>>,
    embedder:Arc<embedder>,
    tool_chains:HashSet<String>,
    consume_produce_apps:HashMap<(String,String),HashSet<String>>,
    object_apps:HashMap<String,HashSet<String>>,
    cp_embeddings:HashMap<String,Vec<f32>>,
    tool_chain_graph:Graph<String, u32>,
    tool_chain_node_map:HashMap<String,NodeIndex>,
    guidelines_embeddings:HashMap<String,Vec<f32>>,
}
impl AppStore{
    pub async fn new(apps_dir:String,embedder:Arc<embedder>)->Arc<Self>{

        let mut app_store=Self{
            apps_dir:apps_dir.clone(),
            apps:RwLock::new(HashMap::new()),
            embedder:embedder.clone(),
            tool_chains:HashSet::new(),
            consume_produce_apps:HashMap::new(),
            
            object_apps:HashMap::new(),
            cp_embeddings:HashMap::new(),
            tool_chain_graph: DiGraph::<String, u32>::new(),
            tool_chain_node_map:HashMap::new(),
            guidelines_embeddings:HashMap::new(),
        };

        app_store.load_apps(apps_dir).await;

        Arc::new(app_store)
    }

    pub fn add_app(
        &self,
        app_toml_path:String
    ){
        
        let app_config_file = fs::read_to_string(app_toml_path.clone()).unwrap();
        // info!("{}",app_config_file);
        let app_config: AppConfig = toml::from_str(&app_config_file).unwrap();
        let handle_name=app_config.get_app_handle_name();
        let app=AppInit{
            app_toml_path,
            app_info:HashMap::new(),
            app_config
        };
        self.apps.write().unwrap().insert(handle_name,app);
    }
    pub fn is_app_exist(&self,app_handle_name:String)->bool{
        let readable_apps=self.apps.read().unwrap();
        let has_app=readable_apps.contains_key(&format!("&{}", app_handle_name)) || readable_apps.contains_key(&app_handle_name);
        has_app
    }

    pub fn clone_app(&self,app_handle_name:String)->Option<App>{
        info!("Cloning app:{}",app_handle_name);
        let readable_apps=self.apps.read().unwrap();
        if readable_apps.contains_key(&format!("&{}", app_handle_name)) || readable_apps.contains_key(&app_handle_name){
            let app_inits=readable_apps.get(&app_handle_name).unwrap();
            Some(App::new(app_inits.app_toml_path.clone(), app_inits.app_info.clone()))
        } else {
            error!("App not found: {}", app_handle_name);
            None
        }
    }
    pub async fn infer_toolchain(&mut self) {
        let mut consumptions_to_produce: HashMap<String,HashSet<(String,String)>> = HashMap::new();
        let mut consumption_apps: HashMap<String,HashSet<String>> = HashMap::new();
        let mut cp_apps: HashMap<(String,String),HashSet<String>> = HashMap::new();
        let mut cp_standalone_apps: HashMap<String,HashSet<String>> = HashMap::new();
        let mut produces: Vec<String> = Vec::new();
        let mut consumptions: Vec<String> = Vec::new();
        let mut blocked_path:HashSet<(String,String)>=HashSet::new();
        let apps_list:Vec<(String,AppInit)>={
            let readable_apps=self.apps.read().unwrap();
        // let mut self.tool_chain_node_map=HashMap::new();
            let mut apps_list_local=Vec::new();

            for (handle_name, app_init) in readable_apps.iter() {
                // info!("App found: {}", handle_name);
                apps_list_local.push((handle_name.clone(), app_init.clone()));
            }
            apps_list_local
        };
        for (app_handle_name,app) in apps_list.iter() {
            
            let desc_embed=self.embedder.get_embeddings(vec![app.get_guidelines()]).await.unwrap();

            self.guidelines_embeddings.insert(app_handle_name.clone(), desc_embed[0].clone());

            for cmd_signature in app.get_cmd_signatures() {
                
                for c in cmd_signature.consumes.iter(){
                    consumptions.push(c.clone());
                    if !self.tool_chain_node_map.contains_key(c){
                        // println!("Adding node to tool chain graph C: {}",c);
                        self.tool_chain_node_map.insert(c.clone(),self.tool_chain_graph.add_node(c.clone()));
                    }
                    if !consumptions_to_produce.contains_key(c){
                        consumptions_to_produce.insert(c.clone(),HashSet::new());
                    }
                    if !consumption_apps.contains_key(c){
                        consumption_apps.insert(c.clone(),HashSet::new());
                    }
                    if !cp_standalone_apps.contains_key(c){
                        cp_standalone_apps.insert(c.clone(),HashSet::new());
                    }
                    
                    cp_standalone_apps.get_mut(c).unwrap().insert(app.app_config.get_app_handle_name().clone());
                    consumption_apps.get_mut(c).unwrap().insert(app.app_config.get_app_handle_name().clone());

                    for p in cmd_signature.produces.iter(){
                        produces.push(p.clone());
                        // println!("Consuming:{}->Producing:{}|App:{}",c,p,app_handle_name);
                        if !self.tool_chain_node_map.contains_key(p){
                            // println!("Adding node to tool chain graph: {}",p);
                            self.tool_chain_node_map.insert(p.clone(),self.tool_chain_graph.add_node(p.clone()));
                        }
                        let n_key=(c.clone(),p.clone());
                        if !cp_apps.contains_key(&n_key){
                            cp_apps.insert(n_key.clone(),HashSet::new());
                        }
                        if !cp_apps.contains_key(&n_key){
                            cp_apps.insert(n_key.clone(),HashSet::new());
                        }
                        if !cp_standalone_apps.contains_key(p){
                            cp_standalone_apps.insert(p.clone(),HashSet::new());
                        }
                        
                        consumptions_to_produce.get_mut(c).unwrap().insert((cmd_signature.action.clone(),p.clone()));
                        blocked_path.insert((p.clone(),c.clone()));
                        cp_apps.get_mut(&n_key).unwrap().insert(app.app_config.get_app_handle_name().clone());
                        cp_standalone_apps.get_mut(p).unwrap().insert(app.app_config.get_app_handle_name().clone());
                        let f=self.tool_chain_node_map.get(c).unwrap();
                        let t=self.tool_chain_node_map.get(p).unwrap();
                        self.tool_chain_graph.add_edge(f.clone(),t.clone(),0);
                        // let t=self.tool_chain_node_map.get(p).unwrap();
                        // g.add_edge(f.clone(),t.clone(),0);
                    }
                }
            }
        }

        consumptions.sort();
        consumptions.dedup();

        produces.sort();
        produces.dedup();

        let consumes_embeddings: Vec<Vec<f32>> = self.embedder.get_embeddings(consumptions.clone()).await.unwrap();

        let produces_embeddings: Vec<Vec<f32>> = self.embedder.get_embeddings(produces.clone()).await.unwrap();

        let consumes_embed_dict: HashMap<String, Vec<f32>> = consumptions.clone()
            .into_iter()
            .zip(consumes_embeddings.into_iter())
            .collect();

        let produces_embed_dict: HashMap<String, Vec<f32>> = produces.clone()
            .into_iter()
            .zip(produces_embeddings.into_iter())
            .collect();
        
        // let mut consumes_mapped: HashMap<String, Vec<String>> = consumes_embed_dict
        //     .iter()
        //     .map(|(k, v)| {
        //         let matched = self.resolve_type(k, v, &produces_embed_dict);
        //         (k.clone(), matched)
        //     })
        //     .collect();

        let produces_mapped: HashMap<String, Vec<String>> = produces_embed_dict
            .iter()
            .map(|(k, v)| {
                let matched = self.resolve_type(k, v, &consumes_embed_dict);
                (k.clone(), matched)
            })
            .collect();

        // for app in readble_apps {
        //     for cmd_signature in app.get_cmd_signatures() {
        //         // for c in cmd_signature.consumes.iter(){
        //         //     if consumes_mapped.contains_key(c){
        //         //         consumes_mapped.get_mut(c).unwrap().extend(cmd_signature.produces.iter().cloned());
        //         //     }
        //         //     else{
        //         //         consumes_mapped.insert(c.to_string(), cmd_signature.produces.iter().cloned().collect());
        //         //     }
        //         // }
        //         for p in cmd_signature.produces.iter(){
        //             if produces_mapped.contains_key(p){
        //                 produces_mapped.get_mut(p).unwrap().extend(cmd_signature.consumes.iter().cloned());
        //             }
        //             else{
        //                 produces_mapped.insert(p.to_string(), cmd_signature.consumes.iter().cloned().collect());
        //             }
        //         }
        //     }
        // }
        
        
        
        // for n in consumptions.iter(){
        // }
        // for n in produces.iter(){
        //     if !self.tool_chain_node_map.contains_key(n){
        //         self.tool_chain_node_map.insert(n,self.tool_chain_graph.add_node(n.clone()));
        //     }
        // }

        // for (c,ps) in consumes_mapped.iter(){
        //     let f=self.tool_chain_node_map.get(c).unwrap();
        //     for p in ps.iter(){
        //         let t=self.tool_chain_node_map.get(p).unwrap();
        //         g.add_edge(f.clone(),t.clone(),0);
        //     }
        // }
        
        // for (app_handle_name,app) in readble_apps.iter() {
        //     for cmd_signature in app.get_cmd_signatures() {
        //         for c in cmd_signature.consumes.iter(){
        //             for p in cmd_signature.produces.iter(){
        //             }
        //         }
        //     }
        // }
        for (p,cs) in produces_mapped.iter(){
            // println!("Producing:{}|{:?}|{:?}",p,cs,self.tool_chain_node_map);
            // println!("Producing:{}|{:?}",p,cs);
            
            let t=self.tool_chain_node_map.get(p).unwrap();
            for c in cs.iter(){
                if blocked_path.contains(&(p.clone(),c.clone())){
                    continue;
                }
                if consumptions_to_produce.contains_key(c){
                    let consuming_app_name=consumption_apps.get(c).unwrap();
                    for (action,np) in consumptions_to_produce.get(c).unwrap().iter(){
                        if p==c || np==p ||np==c{continue;}

                        let old_coversion=format!("{}+action:{}->{}",c,action,p);
                        let new_coversion=format!("{}+action:{}->{}",p,action,np);
                        // info!("Conversions");
                        // info!("{}",old_coversion);
                        // info!("{}",new_coversion);

                        let new_embeds=self.embedder.get_embeddings(vec![old_coversion,new_coversion]).await.unwrap();

                        let new_sim=cosine(&new_embeds[0], &new_embeds[1]);
                        // info!("NEW TOOL CHAIN {}->{}|{}",p,np,new_sim);
                        if new_sim>0.75{
                            for capps in consuming_app_name.iter(){
                                
                                let n_key=(p.clone(),np.clone());
                                if !cp_apps.contains_key(&n_key){
                                    cp_apps.insert(n_key.clone(),HashSet::new());
                                }
                                cp_apps.get_mut(&n_key).unwrap().insert(capps.clone());
                            }

                            let f=self.tool_chain_node_map.get(np).unwrap();
                            self.tool_chain_graph.add_edge(t.clone(),f.clone(),0);
                        }
                    }
                }
            }
        }
        

        // let infered_tool_chains=generate_all_paths(&self.tool_chain_graph);
        // info!("{:?}",cp_apps);
        // self.tool_chains=infered_tool_chains;
        self.consume_produce_apps=cp_apps;
        self.object_apps=cp_standalone_apps;
        self.cp_embeddings.extend(consumes_embed_dict);
        self.cp_embeddings.extend(produces_embed_dict);



    }

    fn shortest_path(
        g: &Graph<String, u32>,
        start: NodeIndex,
        target: NodeIndex,
    ) -> Option<Vec<NodeIndex>> {
        let mut visited = vec![false; g.node_count()];
        let mut parent: Vec<Option<NodeIndex>> = vec![None; g.node_count()];
        let mut queue = VecDeque::new();

        visited[start.index()] = true;
        queue.push_back(start);

        while let Some(node) = queue.pop_front() {
            if node == target {
                // reconstruct path
                let mut path = Vec::new();
                let mut current = Some(node);

                while let Some(n) = current {
                    path.push(n);
                    current = parent[n.index()];
                }

                path.reverse();
                return Some(path);
            }

            for neighbor in g.neighbors(node) {
                if !visited[neighbor.index()] {
                    visited[neighbor.index()] = true;
                    parent[neighbor.index()] = Some(node);
                    queue.push_back(neighbor);
                }
            }
        }

        None
    }
    pub fn get_minimal_tool_chain(&self,c:&String,p:&String)->Option<Vec<String>>{
        let start_node_idx=self.tool_chain_node_map.get(c);
        let end_node_idx=self.tool_chain_node_map.get(p);
        // println!("Finding tool chain for {:?} -> {:?}",start_node_idx,end_node_idx);
        if start_node_idx.is_none() || end_node_idx.is_none(){
            info!("No Node found for {} -> {}",c,p);
            return None;
        }

        let start_node_idx=start_node_idx.unwrap();
        let end_node_idx=end_node_idx.unwrap();

        if let Some(path) = Self::shortest_path(&self.tool_chain_graph, start_node_idx.clone(), end_node_idx.clone()) {
            let tool_chain: Vec<String> = path.iter().map(|idx| self.tool_chain_graph[*idx].clone()).collect();
            Some(tool_chain)
        } else {
            // info!("No tool chain found for {} -> {}",c,p);
            None
        }

    }
    fn all_pairs(&self,set: &HashSet<String>) -> Vec<(String, String)> {
        let items: Vec<_> = set.iter().cloned().collect();
        let mut res = Vec::new();

        for a in &items {
            for b in &items {
                res.push((a.clone(), b.clone()));
            }
        }
        res
    }

    pub async fn resolve_tools(&self,episode_memory:Arc<Memory>,cntxt_content:String,source:Option<&Source>)->(HashSet<String>, String){

        let history_lookup_len=50 as isize;
        let memory_len=episode_memory.get_memory_len().await as isize;
        let mut detected_app_chains:HashSet<String> = HashSet::new();
        let mut include_chain=false;
        let mut detected_intents=HashSet::new();
        let mut detected_objects=HashSet::new();
        let mut conv=Vec::new();
        let cntxt_parts: Vec<String> = cntxt_content
            .split(',')
            .map(|s| s.to_string().trim().to_lowercase())
            .collect();
        detected_objects.extend(cntxt_parts);
        for rec in episode_memory.iter_memory(Some((memory_len-history_lookup_len).max(0) as usize), None,source).await{
            let mem_node_type=rec.get_node_type();
            // info!("mem_node_type:{:?}",mem_node_type);
            if mem_node_type==MemoryNodeType::Message || mem_node_type==MemoryNodeType::ModelResponse{
                let intents=rec.get_node_intents();
                let tags=rec.get_node_tags();

                conv.push(rec.get_content());
                // info!("Content:{}",rec.get_content());
                detected_intents.extend(intents);
                detected_objects.extend(tags);
            }
        }

        info!("detected_objects{:?}",detected_objects);
        let detected_objects_vec:Vec<String>=detected_objects.into_iter().collect();
        
        let types_embeddings: Vec<Vec<f32>> = self.embedder.get_embeddings(detected_objects_vec.clone()).await.unwrap();

        
        let types_embed_dict: HashMap<String, Vec<f32>> = detected_objects_vec.clone()
            .into_iter()
            .zip(types_embeddings.into_iter())
            .collect();

        let types_mapped:HashSet<String> = types_embed_dict
            .iter()
            .map(|(k, v)| {
                let matched = self.resolve_type(k, v, &self.cp_embeddings);
                matched
            })
            .flatten()
            .into_iter().collect();
        
        info!("types_mapped{:?}",types_mapped);
        let mut collected_pairs: HashSet<String> = HashSet::new();
        for (s,t) in self.all_pairs(&types_mapped).iter(){
            if s==t{
                continue;
            }

            let tool_chain=self.get_minimal_tool_chain(s, t);

            if tool_chain.is_none(){
                continue;
            }
            
            let tool_chain=tool_chain.unwrap();
            for obj in tool_chain.clone().iter(){
                if let Some(app)=self.object_apps.get(obj){
                    collected_pairs.extend(app.clone());
                }
            }

            let mut app_chains:Vec<Vec<String>>=Vec::new();
            include_chain=false;

            let tool_chain_window=tool_chain.windows(2);
                
            for window in  tool_chain_window.into_iter(){
                if let [a, b] = window {
                    let nkey=(a.to_string(), b.to_string());

                    if self.consume_produce_apps.contains_key(&nkey){
                        if let Some(app)=self.consume_produce_apps.get(&nkey){
                            collected_pairs.extend(app.clone());

                            
                            let mut temp_chain=Vec::new();

                            for each_app in app.iter(){
                                if app_chains.len()>0{
                                    include_chain=true;
                                    for each_chain in app_chains.iter(){
                                        let mut new_chain=each_chain.clone();
                                        
                                        new_chain.push(format!("&{} {}",each_app,b));
                                        if new_chain.len()>3{
                                            new_chain.remove(0);
                                        }
                                        temp_chain.push(new_chain);

                                        // temp_chain.push(format!("{} -> &{} {}",each_chain,each_app,b));
                                        // temp_chain.push(format!("{} -> &{}",each_chain,each_app));
                                    }
                                }
                                else{
                                    for each_app in app.iter(){
                                        temp_chain.push(vec![format!("&{} {}",each_app,b)]);
                                        // temp_chain.push(format!("&{}",each_app));
                                    }
                                }
                            }
                            app_chains=temp_chain;
                            // app_chains.push(app.clone());
                        }
                    }
                }
            }

            if include_chain{
                detected_app_chains.extend(app_chains.into_iter().map(|chain| chain.join(" -> ")).filter(|chain| !chain.trim().is_empty()));
            }

            





        }


        

        // let mapped_nodes=Vec::new();

        // for tc in self.tool_chain_node_map.iter() {
            


        //     let parts = self.tool_chain_node_map.keys();

        //     // let first_match = parts.iter().position(|&p| types_mapped.contains(p));
        //     let last_match = parts.iter().rposition(|&p| types_mapped.contains(p));

        //     // info!("{:?}",last_match);
        //     if let Some(end) = last_match {
                
        //         let trimmed_sequence = &parts[0..=end];
        //         // info!("trimmed_sequence{:?}",trimmed_sequence);
                
        //         for obj in trimmed_sequence.iter().cloned(){
        //             if let Some(app)=self.object_apps.get(obj){
        //                 collected_pairs.extend(app.clone());
        //             }
        //         }
                
        //         let mut app_chains:Vec<Vec<String>>=Vec::new();
        //         include_chain=false;
                
        //         for window in trimmed_sequence.windows(2) {
        //             if let [a, b] = window {
        //                 let nkey=(a.to_string(), b.to_string());

        //                 if self.consume_produce_apps.contains_key(&nkey){
        //                     if let Some(app)=self.consume_produce_apps.get(&nkey){
        //                         collected_pairs.extend(app.clone());

                                
        //                         let mut temp_chain=Vec::new();

        //                         for each_app in app.iter(){
        //                             if app_chains.len()>0{
        //                                 include_chain=true;
        //                                 for each_chain in app_chains.iter(){
        //                                     let mut new_chain=each_chain.clone();
                                            
        //                                     new_chain.push(format!("&{} {}",each_app,b));
        //                                     if new_chain.len()>3{
        //                                         new_chain.remove(0);
        //                                     }
        //                                     temp_chain.push(new_chain);

        //                                     // temp_chain.push(format!("{} -> &{} {}",each_chain,each_app,b));
        //                                     // temp_chain.push(format!("{} -> &{}",each_chain,each_app));
        //                                 }
        //                             }
        //                             else{
        //                                 for each_app in app.iter(){
        //                                     temp_chain.push(vec![format!("&{} {}",each_app,b)]);
        //                                     // temp_chain.push(format!("&{}",each_app));
        //                                 }
        //                             }
        //                         }
        //                         app_chains=temp_chain;
        //                         // app_chains.push(app.clone());
        //                     }
        //                 }
        //             }
        //         }

        //         if include_chain{
        //             detected_app_chains.extend(app_chains.into_iter().map(|chain| chain.join(" -> ")).filter(|chain| !chain.trim().is_empty()));
        //         }
        //         // detected_app_chains.insert(app_chains.join(" -> "));
        //     }
        // }
        info!("detected_app_chains{:?}",detected_app_chains);
        let app_chain_str=detected_app_chains.iter().cloned().collect::<Vec<String>>().join("\n");
        let conv_str=conv.join("\n");
        let conv_embedding=self.embedder.get_embeddings(vec![conv_str.clone()]).await.unwrap();



        for (app_handle,guideline_embed) in self.guidelines_embeddings.iter(){
            if cosine(&conv_embedding[0], &guideline_embed)>0.75{
                collected_pairs.insert(app_handle.clone());
            }
            else if conv_str.contains(app_handle){
                collected_pairs.insert(app_handle.clone());
            }
        }
        info!("Shortlisted Apps:{:?}",collected_pairs);
        (collected_pairs,app_chain_str)
    }
    fn resolve_type(
        &self,
        candidate: &str,
        candidate_embedding: &[f32],
        target_map: &HashMap<String, Vec<f32>>,
    ) -> Vec<String> {
        let mut matched: Vec<String> = Vec::new();

        // step 1 - exact match
        if target_map.contains_key(candidate) {
            matched.push(candidate.to_string());
            return matched;
        }

        // // step 2 - typo match
        // for (target, _) in target_map.iter() {
        //     if jaro_winkler(candidate, target) > 0.75 {
        //         matched.push(target.clone());
        //     }
        // }

        // if !matched.is_empty() {
        //     matched.dedup();
        //     return matched;
        // }

        // step 3 - semantic match
        for (target, emb) in target_map.iter() {
            let cos_sim=cosine(candidate_embedding, emb);
            // print!("Comparing '{}' with '{}': {}", candidate, target, cos_sim);
            if cos_sim > 0.7 {
                matched.push(target.clone());
            }
        }

        matched.dedup();
        matched
    }


    pub async fn load_apps(&mut self,apps_dir:String){
        let mut matches = Vec::new();
        find_matching_toml_dirs(apps_dir.as_str(),&mut matches);
        for app_path in matches{
            println!("Loading app: {}",app_path);
            self.add_app(app_path);
        }
        
        println!("Infering appchain...");
        self.infer_toolchain().await;
    }





}


fn dfs_all_paths(
    g: &Graph<String, u32>,
    current: NodeIndex,
    visited: &mut Vec<bool>,
    path: &mut Vec<NodeIndex>,
    all_paths: &mut Vec<Vec<NodeIndex>>,
) {
    for neighbor in g.neighbors(current) {
        if !visited[neighbor.index()] {
            visited[neighbor.index()] = true;
            path.push(neighbor);

            // record every path length >= 2 (not just when reaching a sink)
            all_paths.push(path.clone());

            dfs_all_paths(g, neighbor, visited, path, all_paths);

            // backtrack
            path.pop();
            visited[neighbor.index()] = false;
        }
    }
}

fn generate_all_paths(g: &Graph<String, u32>) ->HashSet<String>{
    let mut tool_chains=HashSet::new();
    for start in g.node_indices() {
        let mut visited = vec![false; g.node_count()];
        let mut path = vec![start];
        let mut paths = vec![];
        visited[start.index()] = true;

        dfs_all_paths(g, start, &mut visited, &mut path, &mut paths);

        for path in &paths {
            let s: Vec<String> = path.iter().map(|n| g[*n].clone()).collect();

            let tc=s.join(" -> ");
            tool_chains.insert(tc);
        }
    }
    tool_chains
}

pub fn find_matching_toml_dirs(root: &str, matches: &mut Vec<String>) {
    if let Ok(entries) = fs::read_dir(root) {
        for entry in entries.flatten() {
            let path = entry.path(); 

            if path.is_dir() {
                if let Some(dir_name) = path.file_name().and_then(|n| n.to_str()) {
                    
                    if dir_name.starts_with('.') {
                        continue;
                    }

                    let toml_file = path.join(format!("{}.toml", dir_name));
                    if toml_file.exists() {
                        matches.push(toml_file.to_string_lossy().to_string());
                    }

                    // println!("{}-addpdirs", dir_name);

                    if let Some(sub_path_str) = path.to_str() {
                        find_matching_toml_dirs(sub_path_str, matches);
                    }
                }
            }
        }
    }
}