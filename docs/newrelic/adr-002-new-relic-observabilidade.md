# ADR-002 — Adoção do New Relic como plataforma centralizada de observabilidade

- **Status:** Aceita.
- **Data:** 02/11/2026.

## Contexto

O AutoFlow distribui execução entre API Gateway, Lambda, Kubernetes/EKS, backend Spring Boot, RDS e integrações externas. Diagnosticar falhas de login ou fluxo de ordens de serviço exige acompanhar disponibilidade, latência, erros, estado dos workloads, logs correlacionáveis e eventos de negócio. Logs isolados por serviço não oferecem por si só uma visão consolidada do processamento.

O backend contém instrumentação Java, logs JSON, MDC de `request.id` e emissão de eventos customizados. O root `infra/newrelic` declara integração `nri-bundle`/Fluent Bit, dashboards, condições NRQL e monitor Synthetic, controlados por flags e variáveis de ambiente. Isso demonstra uma decisão arquitetural refletida em código/infraestrutura; não demonstra Apply, ingestão atual, notificações ou operação efetiva dos recursos SaaS.

As forças em oposição são correlação e investigação centralizadas versus dependência de SaaS, custo e limites de ingestão/retenção, exposição de dados em telemetria e manutenção de agente/collector e consultas.

## Decisão

Adotar New Relic como plataforma centralizada declarada para APM Java, métricas e eventos Kubernetes, logs JSON via Fluent Bit, Synthetic, dashboards NRQL, alert conditions e eventos de negócio relacionados a ordens de serviço e integrações.

A integração é habilitável por ambiente e composta por duas partes: o backend injeta o agente Java quando configurado e envia APM/eventos pela License Key; o root Terraform em `autoflow-infra/infra/newrelic` gerencia o chart `nri-bundle` e recursos de conta com Secrets/Variables específicos. A licença de ingestão e a User API key do provider são credenciais distintas. O escopo de coleta de logs, atributos e eventos deve permanecer minimizado e sanitizado.

## Alternativas consideradas

As comparações são retrospectivas; não há evidência de teste ou avaliação formal comparativa de fornecedores, custo ou capacidade.

| Alternativa | Vantagens | Desvantagens e impactos | Razão para não adotar |
|---|---|---|---|
| New Relic (adotada) | Integra APM Java, traces, Kubernetes, logs, NRQL, eventos customizados, dashboards e Synthetic em uma plataforma. | SaaS externo, cobrança/limites de ingestão e retenção, necessidade de cuidar de License Key, agentes, Fluent Bit e compatibilidade das consultas. | A implementação atual já declara essa integração, tornando possível observar a arquitetura heterogênea por uma plataforma comum. Não se alega superioridade por benchmark. |
| AWS CloudWatch | Integração nativa com API Gateway, Lambda e recursos AWS; pode reduzir ferramentas adicionais para telemetria AWS. | Para uma visão equivalente de APM Java, logs estruturados/correlação e eventos de negócio do EKS, seria necessário compor serviços e instrumentações; cobertura completa teria de ser projetada. | Não adotada como plataforma única porque a implementação atual inclui New Relic para APM/Kubernetes/logs e dashboards. Alarmes CloudWatch do API Gateway permanecem complementares. |
| Prometheus + Grafana + Loki e tracing (por exemplo, Tempo/Jaeger) | Composição aberta e maior controle sobre coleta, armazenamento, consultas e retenção. | Exige hospedar, escalar, atualizar, proteger e fazer backup de vários componentes; integrações AWS/Lambda/APM também precisariam ser operadas. | Não escolhida; aumenta a superfície operacional de uma equipe/projeto com stack AWS já distribuída. Nenhum custo comparativo foi medido. |
| Datadog | Plataforma SaaS com recursos equivalentes de APM, logs, métricas, alertas e Synthetic. | Introduz outro fornecedor, agente/configuração e modelo de ingestão/precificação, além de migração e consultas próprias. | Não adotada; não há registro de avaliação formal ou comparação de preços. |

## Consequências positivas

- Reúne sinais de aplicação, Kubernetes e negócio para investigar latência, erro e falhas de processamento.
- APM pode oferecer transações e traces; Fluent Bit coleta stdout estruturado sem forwarding concorrente do agente.
- Dashboards propostos relacionam ordens criadas, duração de etapas, falhas, métricas de pods e latência.
- Synthetic pode acompanhar disponibilidade de uma URL pública e as condições NRQL permitem alertas técnicos/funcionais declarativos.
- Eventos de negócio permitem medir fluxos de OS sem inserir identificadores de OS, documentos ou conteúdo sensível nos atributos declarados.

## Consequências negativas

- Dependência de plataforma SaaS, da conta/região New Relic e de credenciais válidas para ingestão e gestão Terraform.
- Volume, limites, retenção e custo dependem da telemetria efetivamente enviada e do plano New Relic; limites e retenção não são definidos por este root Terraform.
- Agente Java, chart `nri-bundle`, Fluent Bit, filtros, atributos NRQL e dashboards exigem manutenção compatível com versões e schema de eventos.
- Sanitização precisa ocorrer na aplicação, antes da exportação; allowlist de Fluent Bit não corrige texto sensível já presente em `message`.
- Aplicação do chart não garante APM, logs ou métricas disponíveis; ingestão, queries, alertas e destinos de notificação precisam de validação separada.
- Consultas de dashboard e conditions usam atributos de ambiente que precisam corresponder ao schema real emitido pelo agente/eventos.

## Riscos e mitigação

| Risco | Controle existente ou ação necessária |
|---|---|
| CPF/CNPJ, JWT, Authorization, senha ou mensagem privada em log/evento | JSON seguro e conversor de exceção limitado à classe; allowlist Fluent Bit, sem labels/annotations e sem forwarding duplicado; canary tests verificam exclusão de valores sintéticos. Rever mensagens antes de produção. |
| Custo/volume excessivo de logs e métricas | `lowDataMode`, filtro de namespace, allowlist e exclusão de componentes opcionais; revisar ingestão e retenção na conta New Relic. O código não declara orçamento/limite de ingestão. |
| Secret/API key confundida ou vazada | License Key em Kubernetes Secret/Secret Manager e User API key somente como Secret GitHub/provider; não incluir conteúdo em Terraform, logs ou exemplos. |
| Recursos Terraform declarados sem envio de dados | Validar depois de Apply autorizado: APM, `Log`, Kubernetes samples, Synthetic e eventos; não inferir ingestão pela existência do Plan ou release. |
| Alertas sem notificação | Root New Relic não declara notification destination/workflow; configurar e validar destino autorizado em mudança própria, se necessário. |
| Dashboard/alert NRQL incompatível com os atributos APM | Conferir `keyset()` e atributos reais sem expor mensagens; os filtros `environment` e `tags.environment` precisam de confirmação conjunta antes de tratar condições como operacionais. |

## Referências

- [RFC-002 — New Relic como plataforma de observabilidade](rfc-002-new-relic-observabilidade.md)
- [README do root Terraform New Relic](../../infra/newrelic/README.md)
- [Arquitetura de integração API Gateway/EKS](../api-gateway/arquitetura.md)
- [Terraform New Relic: Kubernetes/Fluent Bit](../../infra/newrelic/kubernetes.tf) e [values Helm](../../infra/newrelic/values.yaml)
- [Dashboards](../../infra/newrelic/dashboard.tf), [alertas](../../infra/newrelic/alerts.tf) e [Synthetic](../../infra/newrelic/synthetics.tf)
- [Configuração e política de logs da aplicação](https://github.com/autoflow-fiap/autoflow/blob/develop/backend/newrelic.yml)
