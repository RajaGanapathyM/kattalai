use sqlx::sqlite::{SqlitePool, SqlitePoolOptions, SqliteConnectOptions};
use sqlx::{Execute, Executor, Row};
use std::collections::HashMap;
use std::str::FromStr;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use sqlx::{Sqlite, QueryBuilder};
use serde_json::Value;
use log::{info, warn, error, debug, trace};
use futures::executor::block_on;
// use sqlx::Execute;
/// Database connection wrapper using SQLx with SQLite
#[derive(Clone)]
pub struct DB {
    db_uri: String,
    pub pool: Arc<SqlitePool>,
}

impl DB {
    pub async fn new(db_name:String, max_connections: u32) -> Result<Self, sqlx::Error> {
        let db_uri=format!("sqlite:./data/{}", db_name);
        let connect_options = SqliteConnectOptions::from_str(&db_uri)?
            .create_if_missing(true);

        let pool = SqlitePoolOptions::new()
            .max_connections(max_connections)
            .connect_with(connect_options)
            .await?;

        Ok(DB {
            db_uri,
            pool: Arc::new(pool),
        })
    }
}

pub struct DBTable {
    name: String,
    schema: Value,
    pub pool: Arc<SqlitePool>,
}
impl DBTable{
    pub async fn new(table_name:String,schema:Value,pool: Arc<SqlitePool>,) -> Arc<Self> {
        let mut schema_str = String::new();
        if let Some(object) = schema.as_object() {
            for (col, col_type) in object.iter() {
                schema_str.push_str(&format!("{} {}, ", col, col_type.as_str().unwrap_or("TEXT")));
            }
        } else {
            panic!("Schema must be a JSON object with column names and types!");
        }
        if schema_str.ends_with(", ") {
            schema_str.pop();
            schema_str.pop();
        }
        
        let create_table_query=format!("CREATE TABLE IF NOT EXISTS {} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {})", table_name, schema_str);
        println!("Create query:{}",create_table_query);
        sqlx::query(&create_table_query).execute(pool.as_ref()).await.unwrap();
        Arc::new(Self{
            name:table_name,
            schema,
            pool
        })
    }

    
    pub async fn insert(&self, records: Vec<Value>) -> Result<i64, sqlx::Error>
    {
        if records.is_empty() {
            return Ok(0);
        }

        // 1. Freeze the column order by collecting keys into a Vec
        let columns = if let Some(sch)=self.schema.as_object(){
            sch.keys().into_iter().collect()
        }
        else{
            panic!("SCHEMA NOT PROPER");
            Vec::new()
        };
        // .collect();
        let columns_str = columns.iter().map(|k| k.as_str()).collect::<Vec<_>>().join(", ");

        // 2. Initialize the QueryBuilder
        let mut query_builder= QueryBuilder::new(
            format!("INSERT INTO {} ({}) ", self.name, columns_str)
        );

        // 3. Push the values dynamically for all records in the Vec
        query_builder.push_values(records, |mut b, record| {
            for col in &columns {
                // Using .remove() transfers ownership so we don't need `T: Clone`
                let value = record.get(*col).expect("Record is missing a schema column!").clone();
                b.push_bind(value);
            }
        });

        // 4. Build and execute
        let query = query_builder.build();
        println!("Executing query: {}", query.sql());
        let result = query.execute(self.pool.as_ref()).await;

        if let Ok(res)=result{
            println!("Inserted {:?} rows", res);
            Ok(res.last_insert_rowid())
        }
        else{
            Err(result.err().unwrap())
        }
    }


    pub async fn fetch_all(&self) -> Result<Vec<Value>, sqlx::Error> {
        let query = format!("SELECT * FROM {}", self.name);
        let rows = match sqlx::query(&query).fetch_all(self.pool.as_ref()).await{
            Ok(r)=>r,
            Err(e)=>{
                error!("Failed to fetch records from {}: {:?}", self.name, e);
                Vec::new()
            }
        };
        let mut results = Vec::new();
        for row in rows {
            let mut record = serde_json::Map::new();
            for (col, col_type) in self.schema.as_object().unwrap().iter() {
                let value: Value = match col_type.as_str().unwrap_or("TEXT") {
                    "INTEGER" => row.try_get::<i64, _>(col.as_str()).map(Value::from).unwrap_or(Value::Null),
                    "REAL" => row.try_get::<f64, _>(col.as_str()).map(Value::from).unwrap_or(Value::Null),
                    "TEXT" => row.try_get::<String, _>(col.as_str()).map(Value::from).unwrap_or(Value::Null),
                    "BLOB" => row.try_get::<Vec<u8>, _>(col.as_str()).map(Value::from).unwrap_or(Value::Null),
                    _ => Value::Null,
                };
                record.insert(col.clone(), value);
            }
            results.push(Value::Object(record));
        }
        Ok(results)
    }

    /// Execute a raw SQL query that doesn't return rows
    pub async fn execute(&self, query: &str) -> Result<sqlx::sqlite::SqliteQueryResult, sqlx::Error> {
        sqlx::query(query)
            .execute(self.pool.as_ref())
            .await
    }



    /// Execute a raw SQL query with parameters that doesn't return rows
    pub async fn execute_with_params(
        &self,
        query: &str,
        params: Vec<String>,
    ) -> Result<sqlx::sqlite::SqliteQueryResult, sqlx::Error> {
        let mut query_builder = sqlx::query(query);
        for param in params {
            query_builder = query_builder.bind(param);
        }
        query_builder.execute(self.pool.as_ref()).await
    }

    /// Fetch a single row from the database
    pub async fn fetch_one(
        &self,
        query: &str,
    ) -> Result<Option<sqlx::sqlite::SqliteRow>, sqlx::Error> {
        let row = sqlx::query(query)
            .fetch_optional(self.pool.as_ref())
            .await?;
        Ok(row)
    }


    /// Update records in a table with a WHERE clause
    pub async fn update(
        &self,
        table: &str,
        set_clause: &str,
        where_clause: &str,
        params: Vec<String>,
    ) -> Result<u64, sqlx::Error> {
        let query = format!("UPDATE {} SET {} WHERE {}", table, set_clause, where_clause);

        let mut query_builder = sqlx::query(&query);
        for param in params {
            query_builder = query_builder.bind(param);
        }

        let result = query_builder.execute(self.pool.as_ref()).await?;
        Ok(result.rows_affected())
    }

    /// Delete records from a table with a WHERE clause
    pub async fn delete(&self, table: &str, where_clause: &str, params: Vec<String>) -> Result<u64, sqlx::Error> {
        let query = format!("DELETE FROM {} WHERE {}", table, where_clause);

        let mut query_builder = sqlx::query(&query);
        for param in params {
            query_builder = query_builder.bind(param);
        }

        let result = query_builder.execute(self.pool.as_ref()).await?;
        Ok(result.rows_affected())
    }

    /// Create a new table with a given schema
    pub async fn create_table(&self, create_table_sql: &str) -> Result<(), sqlx::Error> {
        sqlx::query(create_table_sql)
            .execute(self.pool.as_ref())
            .await?;
        Ok(())
    }

    /// Drop a table if it exists
    pub async fn drop_table(&self, table: &str) -> Result<(), sqlx::Error> {
        let query = format!("DROP TABLE IF EXISTS {}", table);
        sqlx::query(&query)
            .execute(self.pool.as_ref())
            .await?;
        Ok(())
    }

    /// Begin a transaction
    pub async fn begin(&self) -> Result<sqlx::Transaction<'static, sqlx::Sqlite>, sqlx::Error> {
        self.pool.begin().await
    }

    // /// Get the current pool statistics
    // pub fn pool_stats(&self) -> PoolStats {
    //     PoolStats {
    //         connections: self.pool.num_acquired(),
    //         size: self.pool.size(),
    //     }
    // }

    /// Close the database connection pool
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

// /// Statistics about the database connection pool
// #[derive(Debug, Clone, Serialize, Deserialize)]
// pub struct PoolStats {
//     pub connections: u32,
//     pub size: u32,
// }
