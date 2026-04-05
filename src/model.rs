// use rust_bert::pipelines::pos_tagging::POSModel;
// use rust_bert::pipelines::ner::NERModel;

use deadpool::unmanaged::{Pool, Object};
use std::sync::{Arc, OnceLock, Mutex};
use whatlang::{detect, Lang};
use nlprule::{Tokenizer, tokenizer, types::Token};

pub struct PosModel{
    tokenizer: Tokenizer,
}
impl PosModel{
    pub async fn new()-> Self {

        

        println!("Loading Tokenizer...");   
        let tokenizer = Tokenizer::new("./model_assets/pos_model/en_tokenizer.bin").unwrap();
        Self{tokenizer}
    }
    
    pub async fn get_pos_tags(&self,documents:&Vec<String>)->Vec<(Vec<String>,Vec<String>)>{
        let mut pos_tags=Vec::new();
        for doc in documents{
            pos_tags.push(self.extract_verbs_nouns(doc).await);

        }
        pos_tags

    }

    
    async fn extract_verbs_nouns(&self,text: &str) -> (Vec<String>, Vec<String>) {
        let lang = detect(text).map(|i| i.lang());

        match lang {
            // nlprule requires paths to the actual downloaded .bin files
            Some(Lang::Eng) => self.extract_with_nlprule(text).await,
            Some(Lang::Deu) => self.extract_with_nlprule(text).await,
            _ => self.extract_with_nlprule(text).await,  // fallback to English
        }
    }

    async fn extract_with_nlprule(&self,text: &str) -> (Vec<String>, Vec<String>) {
        let sentences = self.tokenizer.pipe(text);

        let mut verbs = Vec::new();
        let mut nouns = Vec::new();

        for sentence in sentences {
            for token in sentence.tokens() {
                
                let word = token.word().text().as_str();
                
                if let Some(tag) = token.word().tags().first() {
                    let pos = tag.pos().as_str();
                    // println!("{} → {}", word, pos);

                    if pos.starts_with("NN") || pos.starts_with("SUB") {
                        nouns.push(word.to_string());
                    } else if pos.starts_with("VB") || pos.starts_with("VER") || pos.starts_with("V") {
                        verbs.push(word.to_string());
                    }
                }
            }
        }

        (nouns,verbs)
    }

}



// pub struct PosModel{
//     pos_model: deadpool::unmanaged::Pool<POSModel>,
// }
// impl PosModel{
//     pub async fn new()-> Arc<Self> {
//         let pool_size=5;
//         let pool = Pool::new(pool_size);
//         for _ in 0..pool_size {            
//             let pos_model = tokio::task::spawn_blocking(|| {
//                 POSModel::new(Default::default()).unwrap()
//             })
//             .await
//             .expect("Failed to initialize POSModel in background thread");
//         }

//         Arc::new(Self{pos_model:pool})
//     }
    
//     pub async fn get_pos_tags(&self,documents:&Vec<String>){

//         let output = self.pos_model.get().await.unwrap().predict(documents);

//         for (i, sentence) in output.iter().enumerate() {
//             println!("sentence {}", i);
//             for token in sentence {
//                 println!(" {} → {} ->{}", token.word, token.label,token.score);
//             }
//         }
//     }
// }