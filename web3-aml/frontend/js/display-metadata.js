// Presentation only. Never mutate the source objects used for evidence or export.
export const modelDisplayName = '多维证据风险识别';
export const publicText = value => String(value ?? '').replace(/LightGBM(?:\s*联合风险模型)?/gi, '风险识别模型');
const internalKeys = /^(?:versions?|.*_version|.*_revision|.*_fingerprint|fingerprint|protocol|method|model_name|experiment|experiment_name|experiment_id|profile|schema_version|reporting_revision|config_hash|anchor_index_path|long_path_cases|metadata|source_version|model_artifact|source_artifact|release_source_hashes|raw_claim|.*unscored.*|is_scored|weights?|weighted_probability)$/i;
const internalPath = /(?:artifacts\/(?:experiments|models|tracing)|evidence_tree_v\d|report_claims_v\d|budgeted_relation_tracer_v\d)/i;

export function displaySummary(value) {
  if (Array.isArray(value)) return value.map(displaySummary);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key, item]) => !internalKeys.test(key) && !(typeof item === 'string' && internalPath.test(item)))
    .map(([key, item]) => [key, displaySummary(item)]));
  return typeof value === 'string' ? publicText(value) : value;
}
