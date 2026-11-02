resource "helm_release" "newrelic_kubernetes" {
  count = var.enable_newrelic_kubernetes ? 1 : 0

  name             = "newrelic-kubernetes"
  repository       = "https://helm-charts.newrelic.com"
  chart            = "nri-bundle"
  version          = "8.0.32"
  namespace        = var.newrelic_namespace
  create_namespace = false
  atomic           = false
  wait             = true

  values = [
    file("${path.module}/values.yaml"),
    yamlencode({
      global = {
        cluster                = var.eks_cluster_name
        customSecretName       = var.newrelic_license_secret_name
        customSecretLicenseKey = var.newrelic_license_secret_key
      }
      "newrelic-logging" = {
        fluentBit = {
          config = {
            lowDataModeFilters = <<-FILTER
              [FILTER]
                  Name                kubernetes
                  Alias               kubernetes-enricher
                  Match               kube.*
                  Kube_URL            https://kubernetes.default.svc.cluster.local:443
                  Buffer_Size         $${K8S_BUFFER_SIZE}
                  K8S-Logging.Exclude $${K8S_LOGGING_EXCLUDE}
                  Merge_Log           On
                  Merge_Log_Trim      On
                  Labels              Off
                  Annotations         Off

              [FILTER]
                  Name           nest
                  Alias          kubernetes-attribute-lifter
                  Match          *
                  Operation      lift
                  Nested_under   kubernetes

              [FILTER]
                  Name           record_modifier
                  Alias          node-attributes-enricher-filter
                  Match          *
                  Record         cluster_name "$${CLUSTER_NAME}"
                  Allowlist_key  container_name
                  Allowlist_key  namespace_name
                  Allowlist_key  pod_name
                  Allowlist_key  stream
                  Allowlist_key  log
                  Allowlist_key  timestamp
                  Allowlist_key  level
                  Allowlist_key  logger
                  Allowlist_key  message
                  Allowlist_key  service.name
                  Allowlist_key  deployment.environment
                  Allowlist_key  request.id
                  Allowlist_key  trace.id
                  Allowlist_key  span.id
                  Allowlist_key  exception.type
            FILTER
            extraFilters       = <<-FILTER
              [FILTER]
                  Name   grep
                  Match  kube.*
                  Regex  namespace_name ^${var.newrelic_namespace}$
            FILTER
          }
        }
      }
    })
  ]

  depends_on = [data.aws_eks_cluster.autoflow, data.aws_eks_cluster_auth.auth]
}
