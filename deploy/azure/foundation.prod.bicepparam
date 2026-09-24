using 'foundation.bicep'

param env = 'prod'
param vaultWriterObjectId = '5f48f64f-21d4-411a-afe7-72026aea94ed'   // socrateshlapolosa@socratesbusiness

// Only gpt-5-mini had GlobalStandard quota on 24 Sep 2026 (500k TPM); the other GPT-5.x targets are added
// here once their quota is granted (see the decision record's model table). Capacity unit = 1k TPM.
param deployments = [
  { name: 'text-embedding-3-large', model: 'text-embedding-3-large', format: 'OpenAI', version: '1', sku: 'Standard', capacity: 120 }
  { name: 'gpt-5-mini', model: 'gpt-5-mini', format: 'OpenAI', version: '2025-08-07', sku: 'GlobalStandard', capacity: 200 }
]

// Created once by the operator (python secrets.token_urlsafe → az keyvault secret set), never printed.
param pgAdminPassword = az.getSecret('7ee78ad6-d5bb-484c-8ec9-1673b6553b2a', 'rg-lab-prod', 'kv-lab-prod-i4ov2m', 'pg-admin-password')
