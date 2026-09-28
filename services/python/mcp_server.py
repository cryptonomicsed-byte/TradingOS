from fastmcp import FastMCP
import os
from dotenv import load_dotenv
from sqlalchemy import Column, String, JSON, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import json

load_dotenv()

# Database Setup (Attempt real, fallback to memory)
DB_URL = os.getenv("DATABASE_URL", "sqlite:///:memory:")
try:
    engine = create_engine(DB_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    class Strategy(Base):
        __tablename__ = "strategies"
        id = Column(String, primary_key=True)
        workspace_id = Column(String)
        name = Column(String)
        params_json = Column(JSON)
        created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    Base.metadata.create_all(bind=engine)
    DB_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Database connection failed: {e}. Running without persistence.")
    DB_AVAILABLE = False

# Kafka Setup (Attempt real, fallback to mock)
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
try:
    from kafka import KafkaProducer
    producer = KafkaProducer(
        bootstrap_servers=[KAFKA_BROKER],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        request_timeout_ms=1000
    )
    KAFKA_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Kafka connection failed: {e}. Running in mock mode.")
    KAFKA_AVAILABLE = False

# Initialize FastMCP Server
mcp = FastMCP("TradingOS")

@mcp.tool()
def create_strategy(name: str, params: dict, workspace_id: str):
    """
    Create a new trading strategy and persist it to the database.
    """
    strategy_id = f"strat_{int(datetime.datetime.now().timestamp())}"
    
    if DB_AVAILABLE:
        db = SessionLocal()
        new_strategy = Strategy(id=strategy_id, name=name, params_json=params, workspace_id=workspace_id)
        db.add(new_strategy)
        db.commit()
    
    event = {"event": "strategy_created", "strategy_id": strategy_id, "params": params}
    if KAFKA_AVAILABLE:
        producer.send("kanban.events", event)
    
    return {"strategy_id": strategy_id, "status": "persisted" if DB_AVAILABLE else "mocked"}

@mcp.tool()
def get_ohlcv(ticker: str, timeframe: str = "1h", limit: int = 100):
    """
    Fetch OHLCV data.
    """
    return {"ticker": ticker, "timeframe": timeframe, "limit": limit, "source": "Mock"}

@mcp.tool()
def place_order(ticker: str, side: str, quantity: float, workspace_id: str):
    """
    Place an order and log it to the execution stream.
    """
    event = {
        "event": "order_placed",
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "workspace_id": workspace_id,
        "timestamp": datetime.datetime.now().isoformat()
    }
    if KAFKA_AVAILABLE:
        producer.send("execution.orders", event)
    return {"status": "order_dispatched", "event": event, "kafka": KAFKA_AVAILABLE}

@mcp.tool()
def send_message(to_agent: str, message: str, payload: dict = None):
    """
    Send an A2A message via the agent signals bus.
    """
    msg = {
        "to": to_agent,
        "message": message,
        "payload": payload or {},
        "timestamp": datetime.datetime.now().isoformat()
    }
    if KAFKA_AVAILABLE:
        producer.send("agent.signals", msg)
    return {"status": "message_routed", "target": to_agent, "kafka": KAFKA_AVAILABLE}

if __name__ == "__main__":
    mcp.run()
