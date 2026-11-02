# ADR-001 — API Gateway HTTP API v2 como entrada pública

- **Status:** Aceita.
- **Data:** 13/10/2026.

## Contexto

O sistema precisa de uma entrada HTTP pública única para servir o frontend, encaminhar rotas de negócio ao backend privado e autenticar usuários via Lambda. A topologia anterior incluía Kong no caminho do EKS; o registro histórico da decisão documenta a mudança para uma borda gerenciada. Manter o plano público e a aplicação isolada requer conectar a borda à VPC sem tornar público o ALB ou os NodePorts.

As forças em oposição são unificação do ponto de entrada, integração gerenciada e isolamento de rede versus custo por serviço, latência, dependência da AWS, manutenção de rota/target group e complexidade de VPC Link, ALB e Security Groups. A autenticação de credenciais não deve ser confundida com a autorização de domínio: a Lambda emite JWT; o backend recarrega identidade/perfil e aplica regras atuais.

O API Gateway HTTP API v2, a Lambda, VPC Link v2 e ALB interno estão declarados em Terraform. A configuração versionada não comprova disponibilidade contínua nem implantação atual em produção.

## Decisão

Adotar Amazon API Gateway HTTP API v2 como entrada pública declarada do AutoFlow. `POST /auth/login` integra diretamente com a função Lambda via `AWS_PROXY`, payload format `2.0`, com permissão de invocação restrita à conta e ARN da rota. Frontend e rotas de negócio usam integrações `HTTP_PROXY` pelo VPC Link v2 até listeners de um ALB interno; os target groups encaminham aos NodePorts privados do EKS.

A Lambda e o backend conectam ao RDS privado. A Lambda autentica CPF/CNPJ e senha e emite JWT HS256. O Spring Boot valida assinatura/expiração e consulta usuário, perfil e estado para autorização; claims do token não substituem a política de domínio. A decisão mantém a autenticação de entrada desacoplada do acesso às funções de negócio.

## Alternativas consideradas

A comparação abaixo é retrospectiva. O histórico registra a mudança de gateway, mas não contém avaliação quantitativa de custos, latência ou benchmark formal entre alternativas.

| Alternativa | Vantagens | Desvantagens | Razão para não adotar |
|---|---|---|---|
| API Gateway HTTP API v2 (adotada) | Endpoint gerenciado, integração nativa Lambda e integração privada por VPC Link; permite declarar rotas, CORS, throttling e access logs. | Dependência AWS, custo/limites do serviço e complexidade adicional de VPC Link/ALB; autorização de domínio continua no backend. | Compatível com a topologia existente e separa entrada pública da aplicação privada. |
| API Gateway REST API | Mais opções de configuração e extensões de API Management para cenários que precisem desses recursos. | Maior superfície de configuração e potencial aumento de custo/complexidade; não há necessidade versionada que justifique essa camada adicional. | HTTP API cobre os contratos e integrações declarados; não há evidência de comparação ou benchmark formal. |
| Kong Gateway OSS no EKS | Controle sobre plugins/configuração e independência parcial de recursos específicos de API Gateway. | Operar/atualizar gateway, ingress e plugins junto ao cluster; adicionar consumo e dependência do EKS à borda pública. | O Kong aparece como arquitetura anterior no histórico, mas não é o caminho declarado nesta configuração; não há registro de benchmark formal da troca. |
| ALB público como entrada direta | Menos um serviço de gateway e integração direta com target groups. | Aumenta a superfície exposta do ALB e não oferece por si só o fluxo de login AWS_PROXY; exige tratar CORS, throttling e acesso de forma diferente. | Não preserva o objetivo de entrada gerenciada unificada com Lambda e ALB privado. |

## Consequências positivas

- Login, frontend e rotas de negócio compartilham endpoint público e allowlists de roteamento explícitas.
- A aplicação e o ALB permanecem privados; regras de SG limitam os caminhos entre VPC Link, ALB e nodes.
- A autorização de domínio continua no backend e pode usar perfil/estado atual do banco.
- Terraform e States isolados permitem revisar alterações de borda sem misturar ownership com VPC/EKS, Lambda ou aplicação.

## Consequências negativas

- A rota de tráfego depende de vários serviços e contratos: API Gateway → VPC Link → ALB → target group → NodePort → Service/Pod.
- O tráfego privado entre API Gateway/VPC Link e ALB é HTTP segundo a configuração declarada; TLS termina no endpoint gerenciado público.
- A aplicação depende de AWS para entrada, VPC Link, ALB e EKS, e os custos/limites dependem de uso e conta.
- O backend ainda deve validar JWT e autorização; gateway não elimina a necessidade de proteção no serviço.
- Ajustes de rotas, portas, health checks e Security Groups precisam ser coordenados entre roots Terraform.

## Riscos e mitigação

| Risco | Mitigação existente ou necessária |
|---|---|
| Exposição acidental de serviço interno | ALB `internal`, SG de entrada referenciando VPC Link e NodePorts aceitando somente SG do ALB; confirmar no Plan e no ambiente antes de tráfego. |
| Invocação Lambda fora da rota prevista | `lambda:InvokeFunction` restringe principal, conta e ARN `POST /auth/login`; remover Function URL pública do caminho. |
| JWT válido usado com perfil/status desatualizado | Backend valida assinatura/expiração e carrega usuário/perfil/estado do banco antes da autorização. |
| Drift ou target group sem targets saudáveis | State remoto próprio, Plan vinculado ao run, health checks e alarme de `HealthyHostCount`; `alarm_actions` vazio não entrega notificação. |
| Registro de dados sensíveis em access logs | Formato versionado registra requestId, template de rota, status e latência, sem body, query, IP ou headers. |
| Alteração destrutiva ou custo inesperado | Gates e revisão do Plan; revisar métricas detalhadas, rotas, ALB e VPC Link antes do Apply. |

## Referências

- [RFC-001 — Entrada do AutoFlow com API Gateway](rfc-api-gateway.md)
- [Arquitetura, rede, fluxos e States](arquitetura.md)
- [Terraform HTTP API e integrações](../../infra/api-gateway/main.tf)
- [Catálogo de rotas](../../infra/api-gateway/routes.tf)
- [Módulo de integração privada com EKS](../../infra/api-gateway/modules/private-eks/main.tf)
- [Runbook de operação](runbook.md)
- [Registro original da decisão no histórico](https://github.com/autoflow-fiap/autoflow-infra/commit/31ee40ab16b0802399e62aa990a23ab09c663a79)
