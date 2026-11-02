# Arquitetura final: AutoFlow com Amazon API Gateway

Esta página descreve a arquitetura gerenciada pelos roots Terraform e os fluxos implementados nos quatro repositórios.
As decisões estão em [ADR-001](adr-001-api-gateway.md); os detalhes técnicos, na [RFC](rfc-api-gateway.md).

## Decisão

1. Amazon API Gateway HTTP API v2 é a única entrada pública do AutoFlow.
2. `POST /auth/login` usa integração nativa `AWS_PROXY`, payload `2.0`, para a Lambda existente. A permissão `lambda:InvokeFunction` é restrita à conta e à rota.
3. Rotas de negócio e frontend usam integração `HTTP_PROXY` pelo VPC Link v2 para listeners de um ALB interno.
4. O ALB encaminha aos NodePorts `30081` (Spring Boot) e `30080` (Nginx/Angular), que seguem para Services e Pods do EKS.
5. Lambda e backend acessam o RDS PostgreSQL privado. O JWT HS256 emitido pela Lambda é validado pelo backend; perfis e estado do cliente são verificados no domínio. A HTTP API não declara JWT authorizer.

## C4 — contexto

```mermaid
flowchart LR
  U[Cliente e equipe da oficina] -->|HTTPS| API[Amazon API Gateway HTTP API]
  API -->|Login AWS_PROXY| L[Lambda de autenticação]
  API -->|VPC Link → ALB interno| APP[Frontend Angular e backend Spring Boot no EKS]
  APP -->|PostgreSQL| DB[(RDS PostgreSQL)]
  L -->|PostgreSQL| DB
```

## C4 — contêineres

```mermaid
flowchart LR
  Browser[Navegador Angular] -->|HTTPS, mesma origem| G[HTTP API / stage $default]
  G -->|POST /auth/login, payload 2.0| L[Lambda Python]
  G -->|HTTP_PROXY / VPC Link| ALB[ALB interno]
  ALB --> FE[NodePort 30080 / Nginx Angular]
  ALB --> BE[NodePort 30081 / Spring Boot]
  FE --> SPA[Bundles Angular]
  L --> DB[(RDS PostgreSQL privado)]
  BE --> DB
```

## C4 — componentes

```mermaid
flowchart LR
  Usuario[Cliente ou equipe da oficina]
  Browser[Aplicação Angular no navegador]

  subgraph EDGE[Entrada pública e integração privada]
    API[Amazon API Gateway HTTP API v2]
    LOGIN[Rota POST /auth/login]
    STATIC[Rotas do frontend]
    BUSINESS[Rotas de negócio /api]
    LINK[VPC Link v2]
    ALB[ALB interno<br/>listeners 8080 e 8081]
    API --> LOGIN
    API --> STATIC
    API --> BUSINESS
    STATIC -->|HTTP_PROXY| LINK
    BUSINESS -->|HTTP_PROXY e remove prefixo /api| LINK
    LINK --> ALB
  end

  subgraph AUTH[Autenticação serverless]
    LAMBDA[Lambda Python 3.12]
    VALIDATE[Normalizar CPF/CNPJ e validar senha]
    LOOKUP[Consultar usuário e estado do cliente]
    ISSUE[Emitir JWT HS256]
    LAMBDA --> VALIDATE --> LOOKUP --> ISSUE
  end

  subgraph EKS[Workloads no EKS]
    NGINX[Nginx serve os bundles Angular<br/>NodePort 30080]
    subgraph BACKEND[Backend Spring Boot / NodePort 30081]
      FILTER[Filtro JWT e identidade atual]
      CONTROLLERS[Controllers REST e autorização]
      USECASES[Casos de uso e regras de negócio]
      ADAPTERS[Gateways e adapters de persistência]
      FILTER --> CONTROLLERS --> USECASES --> ADAPTERS
    end
  end

  DB[(RDS PostgreSQL privado)]

  subgraph OBS[Telemetria New Relic declarada, quando habilitada]
    K8S[Integração Kubernetes e Fluent Bit]
    APM[APM Java do backend]
    DASH[Dashboards e alertas NRQL]
    SYNTH[Monitor Synthetic, se configurado]
    K8S --> DASH
    APM --> DASH
  end

  Usuario --> Browser
  Browser -->|HTTPS: login e chamadas da aplicação| API
  LOGIN -->|AWS_PROXY, payload 2.0| LAMBDA
  ISSUE -->|HTTP 200 com JWT ou erro sem token| API
  ALB -->|listener 8080 para NodePort 30080| NGINX
  ALB -->|listener 8081 para NodePort 30081| FILTER
  NGINX -->|HTML, JavaScript e CSS| Browser
  ADAPTERS -->|consultas e gravações| DB
  LOOKUP -->|consulta de credenciais e status| DB
  EKS -.->|métricas e logs, se habilitada| K8S
  BACKEND -.->|APM e eventos, se habilitados| APM
  SYNTH -.->|verifica URL configurada| API
```

O contrato da Lambda usa `cpf_cnpj` e `senha`. O diagrama não implica que o API Gateway valide JWT: a validação e autorização das rotas protegidas são feitas pelo backend Spring Boot. O APM Java é configurado na aplicação; o root `infra/newrelic` gerencia a integração Kubernetes, dashboards, alertas e Synthetic conforme as Variables do Environment. A ordem de provisionamento está no [runbook](../eks-primeiro-provisionamento.md).

## Sequências de comunicação

### 1. Login CPF/CNPJ e emissão de JWT

```mermaid
sequenceDiagram
  actor Cliente
  participant GW as API Gateway HTTP API
  participant L as Lambda de autenticação
  participant DB as RDS PostgreSQL
  participant FE as Frontend Angular
  Cliente->>FE: Informar CPF/CNPJ e senha
  FE->>GW: POST /auth/login {cpf_cnpj, senha}
  GW->>L: AWS_PROXY, payload 2.0
  L->>DB: Consultar usuário/cliente e validar senha/status
  DB-->>L: Registro e resultado da validação
  L-->>GW: HTTP 200 + JWT HS256 ou HTTP 400/401/500 sem token
  GW-->>FE: Resposta JSON de sucesso ou erro
```

### 2. Acesso autenticado ao backend

```mermaid
sequenceDiagram
  actor Usuario as Usuario autenticado
  participant FE as Frontend Angular
  participant GW as API Gateway HTTP API
  participant ALB as ALB interno via VPC Link
  participant BE as Backend Spring Boot no EKS
  participant DB as RDS PostgreSQL
  Usuario->>FE: Acessar funcionalidade
  FE->>GW: GET /api/{rota protegida} + Authorization: Bearer JWT
  GW->>ALB: HTTP_PROXY por VPC Link
  ALB->>BE: Listener 8081 → NodePort 30081. Integração remove o prefixo /api
  BE->>BE: Spring Security valida assinatura e expiração do JWT
  BE->>DB: Recarregar usuário, perfil e estado atuais, depois autorizar a operação
  DB-->>BE: Identidade atual e dados da operação
  BE-->>ALB: Resposta HTTP
  ALB-->>GW: Resposta
  GW-->>FE: Resposta da API
```

### 3. Acesso ao frontend Angular

```mermaid
sequenceDiagram
  actor Usuario as Usuario
  participant Browser as Navegador Angular
  participant GW as API Gateway HTTP API
  participant ALB as ALB interno via VPC Link
  participant Nginx as Nginx no EKS
  Usuario->>Browser: Abrir aplicação ou navegar para rota
  Browser->>GW: GET /, rota frontend ou asset
  GW->>ALB: HTTP_PROXY pelo VPC Link
  ALB->>Nginx: Listener frontend → NodePort 30080
  Nginx-->>ALB: HTML ou asset Angular
  ALB-->>GW: Resposta HTTP
  GW-->>Browser: HTML ou asset
```

As respostas negativas de login não geram JWT. Um JWT válido não substitui as verificações de perfil e estado do cliente no backend.

## C4 — implantação e rede

```mermaid
flowchart TB
  Client[Navegador] -->|HTTPS| API[Amazon API Gateway HTTP API pública]
  API -->|AWS_PROXY payload 2.0| Lambda[Lambda autenticação]
  API -->|VPC Link / ENIs| Link[VPC Link v2]
  subgraph VPC[VPC declarada: 3 subnets públicas e 3 privadas em 3 AZs]
    subgraph Privadas[Subnets privadas]
      Link -->|listeners HTTP 8080/8081| ALB[ALB interno]
      ALB --> TG[Target Groups]
      Lambda[Lambda de autenticação]
      Lambda -->|PostgreSQL 5432| RDS[(RDS PostgreSQL)]
      Apps -->|PostgreSQL 5432| RDS
    end
    subgraph Publicas[Subnets públicas]
      Nodes[Node group gerenciado do EKS]
      Nodes -->|Services → Pods| Apps[Deployments Angular/Nginx e Spring Boot]
    end
    ControlPlane[Plano de controle EKS<br/>subnets públicas e privadas]
    TG -->|SG do ALB → SG dos nodes<br/>NodePorts 30080/30081| Nodes
  end
  LinkSG[SG do VPC Link: saída somente para listeners ALB]
  AlbSG[SG do ALB: entrada do VPC Link, saída para SG dos nodes]
  NodeSG[SG dos nodes: entrada NodePorts somente do SG do ALB]
  DbSG[SG do RDS: PostgreSQL das origens configuradas]
  LinkSG -. associado .-> Link
  AlbSG -. associado .-> ALB
  NodeSG -. associado .-> Nodes
  DbSG -. associado .-> RDS
```

Terraform declara três subnets públicas e três privadas distribuídas em três AZs. O plano de controle do EKS usa subnets dos dois tipos, mas o recurso `aws_eks_node_group` seleciona as subnets públicas. O VPC Link, ALB interno, Lambda e RDS usam subnets privadas. Embora os nodes estejam em subnets públicas, o SG dos nodes aceita as portas 30080/30081 somente do SG do ALB; não há exposição direta dos NodePorts declarada. O SG do ALB permite o SG do VPC Link nos listeners 8080/8081 e saída ao SG dos nodes; o SG do RDS permite PostgreSQL às origens configuradas no root do banco. O tráfego privado VPC Link–ALB usa HTTP; TLS termina no endpoint gerenciado do API Gateway. O [runbook](runbook.md) descreve os passos de provisionamento e validação.

## Rotas e autorização

A matriz executável está em [`routes.tf`](../../infra/api-gateway/routes.tf): 56 rotas de backend, 22 de frontend e uma rota de login. Não há rota catch-all. Rotas de negócio exigem JWT e autorização do Spring; endpoints públicos são somente os declarados no contrato. O API Gateway não substitui a autenticação de domínio.

O frontend chama `/auth/login` e as rotas de negócio no mesmo host. `cors_origins` e `gateway_cors_origins` permanecem allowlists exatas HTTPS para eventuais origens externas; não se usa wildcard.

## States e ownership

| Root proprietário | Responsabilidade final | Variable da State Key no repositório proprietário | Isolamento observado |
|---|---|---|---|
| VPC/EKS (`autoflow-infra/infra`) | VPC, EKS e node group | `AWS_TF_STATE_KEY_INFRA` | O workflow deste repositório exige o prefixo do Environment selecionado. |
| Aplicação (`autoflow/infra`) | Deployments, Services, NodePorts e ConfigMaps | `AWS_TF_STATE_KEY` | O workflow da aplicação consome a Variable; a validação da matriz entre seis roots tem um comando local próprio. |
| RDS (`autoflow-db/infra`) | RDS PostgreSQL e rede do banco | `AWS_TF_STATE_KEY` | O workflow de RDS consome a Variable; a validação da matriz entre seis roots tem um comando local próprio. |
| Lambda (`autoflow-lambda/infra`) | Função Lambda e configuração de execução; a API Gateway HTTP API integra a rota de login | `AWS_TF_STATE_KEY` | O workflow lê a key do Environment selecionado, exige o prefixo do ambiente e valida a separação em relação às keys de VPC/EKS e RDS. O sufixo é externo. |
| API Gateway (`autoflow-infra/infra/api-gateway`) | HTTP API, rotas, integração nativa Lambda, VPC Link, ALB, Target Groups e observabilidade | `AWS_TF_STATE_KEY_GATEWAY` | O workflow deste repositório exige o prefixo do Environment e distingue a key de VPC/EKS e New Relic. |
| New Relic (`autoflow-infra/infra/newrelic`) | Release Helm, dashboards, alertas e Synthetic | `AWS_TF_STATE_KEY_NEWRELIC` | O workflow deste repositório exige o prefixo do Environment e distingue a key de VPC/EKS. |

Para cada Environment, a matriz contém seis keys diferentes, prefixadas por `homolog/` ou `production/`, com sufixos fornecidos externamente. Os consumidores recebem a key exata do root produtor. `terraform_state_contract.py` valida a matriz JSON externa sem acessar AWS; consulte o [runbook de primeiro provisionamento](../eks-primeiro-provisionamento.md) para o procedimento e os valores fornecidos pelos GitHub Environments.

Os states permanecem separados. Nenhum state deve ser editado diretamente ou compartilhado entre contas.

## 4. Provisionamento e operação

O bootstrap do bucket, a validação dos seis States, os gates de Plan/Apply e a ordem de implantação estão descritos no
[runbook do API Gateway](runbook.md), no [runbook de primeiro provisionamento EKS](../eks-primeiro-provisionamento.md)
e no [procedimento de bootstrap S3](../state-bucket-bootstrap.md).
