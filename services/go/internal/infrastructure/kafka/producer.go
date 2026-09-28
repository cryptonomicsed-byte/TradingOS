package kafka

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/segmentio/kafka-go"
	"time"
)

type Producer struct {
	writer *kafka.Writer
}

func NewProducer(broker string, topic string) *Producer {
	return &Producer{
		writer: &kafka.Writer{
			Addr:     kafka.TCP(broker),
			Topic:    topic,
			Balancer: &kafka.LeastBytes{},
			Async:    true,
		},
	}
}

func (p *Producer) Publish(ctx context.Context, key string, value interface{}) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	err = p.writer.WriteMessages(ctx, kafka.Message{
		Key:   []byte(key),
		Value: payload,
		Time:  time.Now(),
	})

	if err != nil {
		return fmt.Errorf("failed to write message to kafka: %w", err)
	}

	return nil
}

func (p *Producer) Close() error {
	return p.writer.Close()
}
