#!/bin/bash

# TradingOS Kafka Topic Initialization

KAFKA_BROKER="localhost:9092"

# Topics to create: name, partitions, replication-factor
TOPICS=(
  "market.ticks:12:1"
  "agent.signals:6:1"
  "kanban.events:6:1"
  "execution.orders:6:1"
  "audit.events:3:1"
)

for TOPIC_INFO in "${TOPICS[@]}"; do
  IFS=":" read -r NAME PARTITIONS REPLICATION <<< "$TOPIC_INFO"
  echo "Creating topic: $NAME with $PARTITIONS partitions..."
  kafka-topics.sh --create --if-not-exists --bootstrap-server "$KAFKA_BROKER" \
    --topic "$NAME" --partitions "$PARTITIONS" --replication-factor "$REPLICATION"
done

echo "Kafka topics initialized."
