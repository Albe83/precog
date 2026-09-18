{{- define "precog.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "precog.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "precog.labels" -}}
app.kubernetes.io/name: {{ include "precog.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "precog.selectorLabels" -}}
app.kubernetes.io/name: {{ include "precog.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "precog.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "precog.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Persistence is on when a PVC is requested or an existing claim is named. */}}
{{- define "precog.modelCache.persistenceEnabled" -}}
{{- if or .Values.modelCache.persistence.enabled .Values.modelCache.persistence.existingClaim -}}true{{- else -}}false{{- end -}}
{{- end -}}

{{- define "precog.modelCache.claimName" -}}
{{- default (include "precog.fullname" .) .Values.modelCache.persistence.existingClaim -}}
{{- end -}}

{{- define "precog.apiKeySecretName" -}}
{{- if .Values.config.existingSecret -}}
{{- .Values.config.existingSecret -}}
{{- else -}}
{{- include "precog.fullname" . -}}
{{- end -}}
{{- end -}}

{{- define "precog.apiKeySecretKey" -}}
{{- default "api-key" .Values.config.existingSecretKey -}}
{{- end -}}
