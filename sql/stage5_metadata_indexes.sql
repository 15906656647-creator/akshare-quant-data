CREATE UNIQUE INDEX IF NOT EXISTS uq_data_quality_issue_issue_key
ON data_quality_issue(issue_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_field_mapping_registry_mapping_key
ON field_mapping_registry(mapping_key);
