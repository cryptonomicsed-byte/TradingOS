# HashiCorp Vault Setup

TradingOS uses HashiCorp Vault for secret management.

## Local Development (Docker)

The `docker-compose.yml` includes a Vault instance running in dev mode for local development.

- **URL:** `http://localhost:8200`
- **Root Token:** `root` (Configured in `docker-compose.yml`)

### Basic CLI Commands

Set the vault address:
```bash
export VAULT_ADDR='http://127.0.0.1:8200'
export VAULT_TOKEN='root'
```

Enable KV secrets engine:
```bash
vault secrets enable -path=secret kv-v2
```

Store a secret:
```bash
vault kv put secret/tradingos/api_keys anthropic_key="sk-..." xai_key="xai-..."
```

Retrieve a secret:
```bash
vault kv get secret/tradingos/api_keys
```
