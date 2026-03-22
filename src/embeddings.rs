use fastembed::{EmbeddingModel, TextEmbedding, UserDefinedEmbeddingModel};
use anyhow::Result;
use rust_bert::pipelines::pos_tagging::POSModel;

use crate::inference;
use futures::executor::block_on;

use deadpool::unmanaged::{Pool, Object};
use std::sync::{Arc, OnceLock, Mutex};
use crate::model::PosModel;

// Declare a global static that can be initialized once at runtime.
pub static GLOBAL_EMBEDDER: OnceLock<Arc<embedder>> = OnceLock::new();
use log::{info, warn, error, debug, trace};
pub struct embedder{
    pooled_model: deadpool::unmanaged::Pool<fastembed::TextEmbedding>,
    pos_model:PosModel
}
impl embedder{

    fn load_local_hf_model(model_assets_dir:String)->UserDefinedEmbeddingModel{
        let model_dir = std::path::PathBuf::from(model_assets_dir);
        let read = |filename: &str| -> Vec<u8> {
                    std::fs::read(model_dir.join(filename)).unwrap()
                };

        
        let user_model = fastembed::UserDefinedEmbeddingModel {
            onnx_file: read("onnx/model.onnx"),
            tokenizer_files: fastembed::TokenizerFiles {
                tokenizer_file:          read("tokenizer.json"),
                config_file:             read("config.json"),
                special_tokens_map_file: read("special_tokens_map.json"),
                tokenizer_config_file:   read("tokenizer_config.json"),
            },
            pooling:              Some(fastembed::Pooling::Mean),
            output_key:           None,
            external_initializers: Vec::new(),
            quantization:    fastembed::QuantizationMode::None,   // was `quantization`
        };

        user_model
    }
    pub async fn new(model_path:String)-> Arc<Self> {
        let pool_size=5;
        let pool = Pool::new(pool_size);
        // let model_dir = std::path::PathBuf::from(model_path);
        // let read = |filename: &str| -> Vec<u8> {
        //             std::fs::read(model_dir.join(filename)).unwrap()
        //         };
        println!("Loading Embedder...");
        for _ in 0..pool_size {
            

            // info!("Path");
            // let user_model = fastembed::UserDefinedEmbeddingModel {
            //     onnx_file: read("onnx/model.onnx"),
            //     tokenizer_files: fastembed::TokenizerFiles {
            //         tokenizer_file:          read("tokenizer.json"),
            //         config_file:             read("config.json"),
            //         special_tokens_map_file: read("special_tokens_map.json"),
            //         tokenizer_config_file:   read("tokenizer_config.json"),
            //     },
            //     pooling:              Some(fastembed::Pooling::Mean),
            //     output_key:           None,
            //     external_initializers: Vec::new(),
            //     quantization:    fastembed::QuantizationMode::None,   // was `quantization`
            // };

            let user_model=embedder::load_local_hf_model(model_path.clone());
            let model = TextEmbedding::try_new_from_user_defined(user_model, Default::default()).unwrap();

            

            pool.add(model).await;
        }
        let pos_model=PosModel::new().await;
        let embedder=Arc::new(Self{pooled_model:pool,pos_model:pos_model});

        GLOBAL_EMBEDDER.get_or_init(||embedder.clone());
        embedder
    }


    pub async fn get_embeddings(&self,documents:Vec<String>)->Result<Vec<Vec<f32>>>{
        self.pooled_model.get().await.unwrap().embed(documents, None)
    }

    pub async fn get_pos_tags(&self,documents:&Vec<String>)->Vec<(Vec<String>,Vec<String>)>{
        self.pos_model.get_pos_tags(documents).await

    }
}