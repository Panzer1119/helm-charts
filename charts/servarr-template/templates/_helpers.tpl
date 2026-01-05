{{/*
Expand the name of the chart.
*/}}
{{- define "servarr-template.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "servarr-template.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "servarr-template.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "servarr-template.labels" -}}
helm.sh/chart: {{ include "servarr-template.chart" .root }}
{{ include "servarr-template.selectorLabels" (dict "root" .root "instance" .instance) }}
{{- if .root.Chart.AppVersion }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "servarr-template.selectorLabels" -}}
app.kubernetes.io/name: {{ include "servarr-template.name" .root }}
app.kubernetes.io/instance: {{ include "servarr-template.instanceName" (dict "root" .root "instance" .instance) }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "servarr-template.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "servarr-template.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "servarr-template.instanceName" -}}
{{ printf "%s-%s" .root.Release.Name .instance.name }}
{{- end }}

{{- define "servarr-template.instanceFullname" -}}
{{ printf "%s-%s" (include "servarr-template.fullname" .root) .instance.name }}
{{- end }}


{{/*
API key secret name.
*/}}
{{- define "servarr-template.syncApiKeySecretName" }}
{{- if .instance.syncApiKeySecret.existingSecret }}
{{- .instance.syncApiKeySecret.existingSecret }}
{{- else if .instance.syncApiKeySecret.name }}
{{- .instance.syncApiKeySecret.name }}
{{- else }}
{{- printf "%s-apikey" (include "servarr-template.fullname" .root) }}
{{- end }}
{{- end }}

{{/*
API key secret data key.
*/}}
{{- define "servarr-template.syncApiKeySecretKey" }}
{{- default "apiKey" .instance.syncApiKeySecret.key }}
{{- end }}
