-- Generated companion for b47e5c32f186. Applied by the Python migration.

CREATE OR REPLACE FUNCTION public._cosmas_pk_text_expr(p_alias text, p_cols text[])
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $$
  SELECT CASE
    WHEN array_length(p_cols, 1) = 1 THEN format('%I.%I::text', p_alias, p_cols[1])
    ELSE (
      SELECT string_agg(format('%I.%I::text', p_alias, col), ' || '','' || ' ORDER BY ord)
        FROM unnest(p_cols) WITH ORDINALITY AS u(col, ord)
    )
  END;
$$;

CREATE OR REPLACE FUNCTION public._cosmas_patient_deletion_classes()
RETURNS TABLE(kind text, table_name text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT * FROM (VALUES
            ('owned', 'action_revisions'),
            ('owned', 'appointment_executions'),
            ('owned', 'appointment_observations'),
            ('owned', 'appointment_receipts'),
            ('owned', 'appointment_work'),
            ('owned', 'artifacts'),
            ('owned', 'calendar_import_requests'),
            ('owned', 'calendar_import_revocations'),
            ('owned', 'calendar_import_snapshots'),
            ('owned', 'calendar_import_source_reviews'),
            ('owned', 'conversation_read_markers'),
            ('owned', 'decisions'),
            ('owned', 'efax_inbound_acquisitions'),
            ('owned', 'efax_inbound_image_revisions'),
            ('owned', 'efax_inbound_invocations'),
            ('owned', 'efax_inbound_outcomes'),
            ('owned', 'efax_inbound_source_reviews'),
            ('owned', 'ehr_athena_core_patient_grants'),
            ('owned', 'ehr_athena_medication_patient_grants'),
            ('owned', 'ehr_fhir_patient_grants'),
            ('owned', 'ehr_read_requests'),
            ('owned', 'ehr_read_snapshots'),
            ('owned', 'ehr_read_source_reviews'),
            ('owned', 'encounter_workspaces'),
            ('owned', 'fax_inbound_attempts'),
            ('owned', 'fax_inbound_dispatches'),
            ('owned', 'fax_inbound_images'),
            ('owned', 'fax_inbound_outcomes'),
            ('owned', 'fax_inbound_source_reviews'),
            ('owned', 'finance_command_receipts'),
            ('owned', 'finance_customer_versions'),
            ('owned', 'finance_provider_observations'),
            ('owned', 'finance_read_claims'),
            ('owned', 'finance_reopen_facts'),
            ('owned', 'finance_setup_receipts'),
            ('owned', 'finance_setup_revisions'),
            ('owned', 'finance_setups'),
            ('owned', 'finance_submit_claims'),
            ('owned', 'finance_work_revisions'),
            ('owned', 'follow_up_receipts'),
            ('owned', 'follow_up_sources'),
            ('owned', 'google_calendar_private_source_reviews'),
            ('owned', 'google_calendar_source_reviews'),
            ('owned', 'google_message_source_reviews'),
            ('owned', 'inbox_events'),
            ('owned', 'inbox_handoff_receipts'),
            ('owned', 'inbox_items'),
            ('owned', 'inbox_sources'),
            ('owned', 'membership_command_retirements'),
            ('owned', 'membership_receipts'),
            ('owned', 'membership_work'),
            ('owned', 'microsoft_calendar_source_reviews'),
            ('owned', 'microsoft_message_source_reviews'),
            ('owned', 'model_usage_observations'),
            ('owned', 'model_work_admissions'),
            ('owned', 'operations'),
            ('owned', 'patient_links'),
            ('owned', 'portal_setup_receipts'),
            ('owned', 'portal_setup_revisions'),
            ('owned', 'portal_work'),
            ('owned', 'portal_work_claims'),
            ('owned', 'portal_work_observations'),
            ('owned', 'portal_work_receipts'),
            ('owned', 'portal_work_reopens'),
            ('owned', 'private_recording_finishes'),
            ('owned', 'private_recording_links'),
            ('owned', 'private_recording_transfer_attempts'),
            ('owned', 'private_recording_transfer_rejections'),
            ('owned', 'private_recording_transfer_sessions'),
            ('owned', 'private_recording_transfers'),
            ('owned', 'private_recording_visit_bindings'),
            ('owned', 'private_recordings'),
            ('owned', 'research_runs'),
            ('owned', 'research_saves'),
            ('owned', 'scheduling_patient_accounts'),
            ('owned', 'scheduling_patient_mapping_reviews'),
            ('owned', 'scheduling_patient_setup_requests'),
            ('owned', 'scheduling_patient_setup_snapshots'),
            ('owned', 'tickets'),
            ('owned', 'vendor_artifact_attempts'),
            ('owned', 'vendor_artifacts'),
            ('owned', 'vendor_command_receipts'),
            ('owned', 'vendor_command_retirements'),
            ('owned', 'vendor_correspondence_versions'),
            ('owned', 'vendor_preparation_retirements'),
            ('owned', 'vendor_provider_observations'),
            ('owned', 'vendor_read_claims'),
            ('owned', 'vendor_setup_receipts'),
            ('owned', 'vendor_setup_revisions'),
            ('owned', 'vendor_setups'),
            ('owned', 'vendor_submit_claims'),
            ('owned', 'vendor_work'),
            ('owned', 'vendor_work_revisions'),
            ('owned', 'work_handoffs'),
            ('owned', 'workspace_appointment_links'),
            ('owned', 'workspace_core_note_sources'),
            ('owned', 'workspace_entries'),
            ('owned', 'workspace_handoff_attempts'),
            ('owned', 'workspace_handoff_reviews'),
            ('owned', 'workspace_handoff_revisions'),
            ('owned', 'workspace_handoffs'),
            ('owned', 'workspace_note_reviews'),
            ('owned', 'workspace_notes'),
            ('owned', 'workspace_replies'),
            ('owned', 'workspace_title_revisions'),
            ('preserve', 'alembic_version'),
            ('preserve', 'audit_events'),
            ('preserve', 'patient_deletion_admin_bindings'),
            ('preserve', 'patient_deletion_in_progress'),
            ('preserve', 'patient_deletion_pending_files'),
            ('shared', 'box_contexts'),
            ('shared', 'capability_configs'),
            ('shared', 'capture_upload_proxies'),
            ('shared', 'core_capture_accounts'),
            ('shared', 'efax_inbound_grants'),
            ('shared', 'efax_inbound_observation_requests'),
            ('shared', 'efax_inbound_observations'),
            ('shared', 'efax_inbound_receipts'),
            ('shared', 'ehr_practice_resource_scopes'),
            ('shared', 'ehr_read_bindings'),
            ('shared', 'elation_sandbox_installation_receipts'),
            ('shared', 'elation_sandbox_quota_minutes'),
            ('shared', 'elation_sandbox_quotas'),
            ('shared', 'external_identities'),
            ('shared', 'fax_inbound_commands'),
            ('shared', 'fax_inbound_grants'),
            ('shared', 'fax_inbound_observations'),
            ('shared', 'finance_connection_versions'),
            ('shared', 'finance_event_candidates'),
            ('shared', 'google_calendar_observation_requests'),
            ('shared', 'google_connection_attempts'),
            ('shared', 'google_connection_credentials'),
            ('shared', 'google_message_read_requests'),
            ('shared', 'microsoft_calendar_observation_requests'),
            ('shared', 'microsoft_connection_attempts'),
            ('shared', 'microsoft_connection_credentials'),
            ('shared', 'microsoft_message_read_requests'),
            ('shared', 'portal_setups'),
            ('exclusive', 'google_calendar_snapshots'),
            ('exclusive', 'google_message_snapshots'),
            ('exclusive', 'microsoft_calendar_snapshots'),
            ('exclusive', 'microsoft_message_snapshots'),
            ('shared', 'practice_access_requests'),
            ('shared', 'practice_invitations'),
            ('shared', 'practice_invite_revocations'),
            ('shared', 'practice_invite_uses'),
            ('shared', 'practice_owner_reservations'),
            ('shared', 'practice_setup_profiles'),
            ('shared', 'principals'),
            ('shared', 'provider_bots'),
            ('shared', 'provider_team_revisions'),
            ('shared', 'routine_revisions'),
            ('shared', 'routine_runs'),
            ('shared', 'scheduling_accounts'),
            ('shared', 'scheduling_enrollments'),
            ('shared', 'scheduling_login_attempts'),
            ('shared', 'scheduling_login_credentials'),
            ('shared', 'vendor_connection_versions'),
            ('shared', 'vendor_event_candidates')
  ) AS t(kind, table_name);
$$;

-- EXCLUSIVE_CONTENT review edges. patient_col NULL means the review table only
-- participates in retain checks (never discovers candidates for this patient).
CREATE OR REPLACE FUNCTION public._cosmas_patient_deletion_exclusive_refs()
RETURNS TABLE(content_table text, review_table text, snapshot_col text, patient_col text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT * FROM (VALUES
            ('google_message_snapshots', 'google_message_source_reviews', 'snapshot_id', 'patient_link_id'),
            ('microsoft_message_snapshots', 'microsoft_message_source_reviews', 'snapshot_id', 'patient_link_id'),
            ('google_calendar_snapshots', 'google_calendar_source_reviews', 'snapshot_id', 'patient_link_id'),
            ('google_calendar_snapshots', 'google_calendar_private_source_reviews', 'snapshot_id', NULL),
            ('microsoft_calendar_snapshots', 'microsoft_calendar_source_reviews', 'snapshot_id', 'patient_link_id')
  ) AS t(content_table, review_table, snapshot_col, patient_col);
$$;


CREATE OR REPLACE FUNCTION public._cosmas_patient_deletion_active()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.patient_deletion_in_progress WHERE txid = txid_current()
  );
$$;

CREATE OR REPLACE FUNCTION public._cosmas_patient_deletion_build_plan(p_patient uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $p$
DECLARE
  v_owned text[] := ARRAY(SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind = 'owned' ORDER BY 1);
  v_preserve text[] := ARRAY(SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind = 'preserve' ORDER BY 1);
  v_shared text[] := ARRAY(SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind = 'shared' ORDER BY 1);
  v_exclusive text[] := ARRAY(SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind = 'exclusive' ORDER BY 1);
  v_declared text[] := ARRAY[
    'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
    'fk_ehr_read_request_parent',
    'fk_inbox_current_source',
    'inbox_sources_item_id_box_id_owner_id_fkey',
    'fk_vendor_supersedes_scope',
    'vendor_work_revisions_ticket_id_workspace_id_box_id_owner__fkey'
  ];
  v_reachable text[] := ARRAY['patient_links'];
  v_dirty text[] := ARRAY['patient_links'];
  v_table text;
  v_child text;
  v_parent text;
  v_unclassified text;
  rec record;
  edge record;
  v_plan jsonb := '{}'::jsonb;
  v_pks text[];
  v_new text[];
  v_parent_pks text[];
  v_sql text;
  v_steps int := 0;
  v_counts jsonb := '{}'::jsonb;
  v_retained jsonb := '{}'::jsonb;
  v_child_pk text;
  v_parent_pk text;
  v_join text;
  v_edges jsonb := '[]'::jsonb;
  v_seen text[];
  v_queue text[];
  v_node text;
  v_found boolean;
  v_child_cols text[];
  v_parent_cols text[];
  v_child_pk_cols text[];
  v_parent_pk_cols text[];
  v_candidates text[];
  v_delete_ids text[];
  v_keep int;
  v_id text;
  v_other boolean;
  xref record;
BEGIN
  IF p_patient IS NULL THEN
    RAISE EXCEPTION 'patient records could not be deleted';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.patient_links WHERE id = p_patient) THEN
    RAISE EXCEPTION 'patient not found';
  END IF;

  LOOP
    v_steps := v_steps + 1;
    IF v_steps > 10000 THEN
      RAISE EXCEPTION 'patient records could not be deleted';
    END IF;
    EXIT WHEN coalesce(array_length(v_dirty, 1), 0) = 0;
    v_table := v_dirty[1];
    v_dirty := v_dirty[2:];
    FOR v_child IN
      SELECT child.relname
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
        JOIN pg_catalog.pg_class parent ON parent.oid = con.confrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
        JOIN pg_catalog.pg_namespace pns ON pns.oid = parent.relnamespace
       WHERE con.contype = 'f'
         AND ns.nspname = 'public' AND pns.nspname = 'public'
         AND parent.relname = v_table
         AND child.relkind IN ('r', 'p')
    LOOP
      IF NOT (v_child = ANY (v_reachable)) THEN
        v_reachable := array_append(v_reachable, v_child);
        v_dirty := array_append(v_dirty, v_child);
      END IF;
    END LOOP;
  END LOOP;

  SELECT x INTO v_unclassified
    FROM unnest(v_reachable) AS x
   WHERE NOT (
     x = ANY (v_owned)
     OR x = ANY (v_preserve)
     OR x = ANY (v_shared)
     OR x = ANY (v_exclusive)
   )
   ORDER BY 1 LIMIT 1;
  IF v_unclassified IS NOT NULL THEN
    RAISE EXCEPTION 'schema not classified for patient deletion';
  END IF;

  SELECT coalesce(jsonb_agg(row_to_json(e)::jsonb ORDER BY e.oid), '[]'::jsonb)
    INTO v_edges
    FROM (
      SELECT con.oid,
             child.relname AS child_table,
             parent.relname AS parent_table,
             con.conname::text AS conname,
             (SELECT array_agg(a.attname ORDER BY k.ord)
                FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS child_cols,
             (SELECT array_agg(a.attname ORDER BY k.ord)
                FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_catalog.pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum) AS parent_cols,
             (SELECT array_agg(a.attname ORDER BY k.ord)
                FROM unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum) AS child_pk_cols,
             (SELECT array_agg(a.attname ORDER BY k.ord)
                FROM unnest(ppk.conkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_catalog.pg_attribute a ON a.attrelid = ppk.conrelid AND a.attnum = k.attnum) AS parent_pk_cols
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
        JOIN pg_catalog.pg_class parent ON parent.oid = con.confrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
        JOIN pg_catalog.pg_namespace pns ON pns.oid = parent.relnamespace
        JOIN pg_catalog.pg_constraint pk ON pk.conrelid = child.oid AND pk.contype = 'p'
        JOIN pg_catalog.pg_constraint ppk ON ppk.conrelid = parent.oid AND ppk.contype = 'p'
       WHERE con.contype = 'f'
         AND ns.nspname = 'public' AND pns.nspname = 'public'
         AND child.relname = ANY (v_owned)
         AND parent.relname = ANY (v_owned)
         AND child.relkind IN ('r', 'p')
         AND child.relname = ANY (v_reachable)
         AND parent.relname = ANY (v_reachable)
    ) e;

  FOR edge IN
    SELECT * FROM jsonb_to_recordset(v_edges) AS x(
      child_table text,
      parent_table text,
      conname text,
      child_cols text[],
      parent_cols text[],
      child_pk_cols text[],
      parent_pk_cols text[]
    )
  LOOP
    IF edge.child_table = edge.parent_table THEN
      CONTINUE;
    END IF;
    IF edge.conname = ANY (v_declared) THEN
      CONTINUE;
    END IF;
    v_seen := ARRAY[edge.parent_table];
    v_queue := ARRAY[edge.parent_table];
    v_found := FALSE;
    v_steps := 0;
    WHILE coalesce(array_length(v_queue, 1), 0) > 0 LOOP
      v_steps := v_steps + 1;
      IF v_steps > 10000 THEN
        RAISE EXCEPTION 'patient records could not be deleted';
      END IF;
      v_node := v_queue[1];
      v_queue := v_queue[2:];
      IF v_node = edge.child_table THEN
        v_found := TRUE;
        EXIT;
      END IF;
      FOR rec IN
        SELECT (e ->> 'parent_table') AS parent
          FROM jsonb_array_elements(v_edges) AS e
         WHERE (e ->> 'child_table') = v_node
           AND (e ->> 'child_table') IS DISTINCT FROM (e ->> 'parent_table')
      LOOP
        IF NOT (rec.parent = ANY (v_seen)) THEN
          v_seen := array_append(v_seen, rec.parent);
          v_queue := array_append(v_queue, rec.parent);
        END IF;
      END LOOP;
    END LOOP;
    IF v_found THEN
      RAISE EXCEPTION 'schema not classified for patient deletion';
    END IF;
  END LOOP;

  v_plan := jsonb_build_object('patient_links', to_jsonb(ARRAY[p_patient::text]));
  v_dirty := ARRAY['patient_links'];
  v_steps := 0;
  WHILE coalesce(array_length(v_dirty, 1), 0) > 0 LOOP
    v_steps := v_steps + 1;
    IF v_steps > 10000 THEN
      RAISE EXCEPTION 'patient records could not be deleted';
    END IF;
    v_parent := v_dirty[1];
    v_dirty := v_dirty[2:];
    v_parent_pks := ARRAY(
      SELECT jsonb_array_elements_text(COALESCE(v_plan -> v_parent, '[]'::jsonb))
    );
    IF coalesce(array_length(v_parent_pks, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    FOR edge IN
      SELECT * FROM jsonb_to_recordset(v_edges) AS x(
        child_table text,
        parent_table text,
        conname text,
        child_cols text[],
        parent_cols text[],
        child_pk_cols text[],
        parent_pk_cols text[]
      )
     WHERE parent_table = v_parent
    LOOP
      v_child_cols := edge.child_cols;
      v_parent_cols := edge.parent_cols;
      v_child_pk_cols := edge.child_pk_cols;
      v_parent_pk_cols := edge.parent_pk_cols;
      v_child_pk := public._cosmas_pk_text_expr('c', v_child_pk_cols);
      v_parent_pk := public._cosmas_pk_text_expr('p', v_parent_pk_cols);
      v_join := (
        SELECT string_agg(
          format('c.%I IS NOT DISTINCT FROM p.%I', v_child_cols[ord], v_parent_cols[ord]),
          ' AND ' ORDER BY ord
        )
        FROM generate_subscripts(v_child_cols, 1) AS ord
      );
      v_sql := format(
        'SELECT ARRAY(SELECT DISTINCT %s FROM public.%I c JOIN public.%I p ON %s WHERE %s = ANY ($1))',
        v_child_pk, edge.child_table, edge.parent_table, v_join, v_parent_pk
      );
      EXECUTE v_sql INTO v_new USING v_parent_pks;
      v_new := COALESCE(v_new, ARRAY[]::text[]);
      v_pks := ARRAY(
        SELECT DISTINCT jsonb_array_elements_text(COALESCE(v_plan -> edge.child_table, '[]'::jsonb))
        ORDER BY 1
      );
      SELECT ARRAY(SELECT DISTINCT x FROM unnest(COALESCE(v_pks, ARRAY[]::text[]) || v_new) AS x ORDER BY 1)
        INTO v_new;
      IF v_new IS DISTINCT FROM COALESCE(v_pks, ARRAY[]::text[]) THEN
        v_plan := v_plan || jsonb_build_object(edge.child_table, to_jsonb(v_new));
        IF NOT (edge.child_table = ANY (v_dirty)) THEN
          v_dirty := array_append(v_dirty, edge.child_table);
        END IF;
      END IF;
    END LOOP;
  END LOOP;

  -- Also collect PATIENT_OWNED rows keyed directly by patient_link_id.
  FOR v_table IN
    SELECT c.relname
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attname = 'patient_link_id' AND NOT a.attisdropped
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p')
       AND c.relname = ANY (v_owned)
     ORDER BY 1
  LOOP
    SELECT array_agg(a.attname ORDER BY k.ord)
      INTO v_child_pk_cols
      FROM pg_catalog.pg_constraint pk
      JOIN pg_catalog.pg_class c ON c.oid = pk.conrelid
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      JOIN unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
      JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum
     WHERE pk.contype = 'p' AND n.nspname = 'public' AND c.relname = v_table;
    IF v_child_pk_cols IS NULL THEN
      CONTINUE;
    END IF;
    v_child_pk := public._cosmas_pk_text_expr('t', v_child_pk_cols);
    v_sql := format(
      'SELECT ARRAY(SELECT DISTINCT %s FROM public.%I t WHERE t.patient_link_id = $1 ORDER BY 1)',
      v_child_pk, v_table
    );
    EXECUTE v_sql INTO v_new USING p_patient;
    v_new := COALESCE(v_new, ARRAY[]::text[]);
    v_pks := ARRAY(
      SELECT DISTINCT jsonb_array_elements_text(COALESCE(v_plan -> v_table, '[]'::jsonb))
      ORDER BY 1
    );
    SELECT ARRAY(SELECT DISTINCT x FROM unnest(COALESCE(v_pks, ARRAY[]::text[]) || v_new) AS x ORDER BY 1)
      INTO v_new;
    IF coalesce(array_length(v_new, 1), 0) > 0 THEN
      v_plan := v_plan || jsonb_build_object(v_table, to_jsonb(v_new));
    END IF;
  END LOOP;

  -- Re-expand FK children after direct patient_link_id collection.
  v_dirty := ARRAY(SELECT DISTINCT jsonb_object_keys(v_plan) ORDER BY 1);
  v_steps := 0;
  WHILE coalesce(array_length(v_dirty, 1), 0) > 0 LOOP
    v_steps := v_steps + 1;
    IF v_steps > 10000 THEN
      RAISE EXCEPTION 'patient records could not be deleted';
    END IF;
    v_parent := v_dirty[1];
    v_dirty := v_dirty[2:];
    v_parent_pks := ARRAY(
      SELECT DISTINCT jsonb_array_elements_text(COALESCE(v_plan -> v_parent, '[]'::jsonb))
      ORDER BY 1
    );
    IF coalesce(array_length(v_parent_pks, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    FOR edge IN
      SELECT * FROM jsonb_to_recordset(v_edges) AS x(
        child_table text,
        parent_table text,
        conname text,
        child_cols text[],
        parent_cols text[],
        child_pk_cols text[],
        parent_pk_cols text[]
      )
     WHERE parent_table = v_parent
    LOOP
      v_child_cols := edge.child_cols;
      v_parent_cols := edge.parent_cols;
      v_child_pk_cols := edge.child_pk_cols;
      v_parent_pk_cols := edge.parent_pk_cols;
      v_child_pk := public._cosmas_pk_text_expr('c', v_child_pk_cols);
      v_parent_pk := public._cosmas_pk_text_expr('p', v_parent_pk_cols);
      v_join := (
        SELECT string_agg(
          format('c.%I IS NOT DISTINCT FROM p.%I', v_child_cols[ord], v_parent_cols[ord]),
          ' AND ' ORDER BY ord
        )
        FROM generate_subscripts(v_child_cols, 1) AS ord
      );
      v_sql := format(
        'SELECT ARRAY(SELECT DISTINCT %s FROM public.%I c JOIN public.%I p ON %s WHERE %s = ANY ($1))',
        v_child_pk, edge.child_table, edge.parent_table, v_join, v_parent_pk
      );
      EXECUTE v_sql INTO v_new USING v_parent_pks;
      v_new := COALESCE(v_new, ARRAY[]::text[]);
      v_pks := ARRAY(
        SELECT DISTINCT jsonb_array_elements_text(COALESCE(v_plan -> edge.child_table, '[]'::jsonb))
        ORDER BY 1
      );
      SELECT ARRAY(SELECT DISTINCT x FROM unnest(COALESCE(v_pks, ARRAY[]::text[]) || v_new) AS x ORDER BY 1)
        INTO v_new;
      IF v_new IS DISTINCT FROM COALESCE(v_pks, ARRAY[]::text[]) THEN
        v_plan := v_plan || jsonb_build_object(edge.child_table, to_jsonb(v_new));
        IF NOT (edge.child_table = ANY (v_dirty)) THEN
          v_dirty := array_append(v_dirty, edge.child_table);
        END IF;
      END IF;
    END LOOP;
  END LOOP;

  FOR v_table IN SELECT * FROM unnest(v_owned) ORDER BY 1 LOOP
    v_pks := ARRAY(SELECT jsonb_array_elements_text(COALESCE(v_plan -> v_table, '[]'::jsonb)));
    IF coalesce(array_length(v_pks, 1), 0) > 0 THEN
      v_counts := v_counts || jsonb_build_object(v_table, array_length(v_pks, 1));
    END IF;
  END LOOP;

  -- EXCLUSIVE_CONTENT: delete when every review referencing the row is this patient's.
  FOR v_table IN SELECT * FROM unnest(v_exclusive) ORDER BY 1 LOOP
    v_candidates := ARRAY[]::text[];
    FOR xref IN
      SELECT * FROM public._cosmas_patient_deletion_exclusive_refs()
       WHERE content_table = v_table AND patient_col IS NOT NULL
    LOOP
      v_sql := format(
        'SELECT ARRAY(SELECT DISTINCT %I::text FROM public.%I WHERE %I = $1 ORDER BY 1)',
        xref.snapshot_col, xref.review_table, xref.patient_col
      );
      EXECUTE v_sql INTO v_new USING p_patient;
      v_new := COALESCE(v_new, ARRAY[]::text[]);
      SELECT ARRAY(
        SELECT DISTINCT x FROM unnest(COALESCE(v_candidates, ARRAY[]::text[]) || v_new) AS x ORDER BY 1
      ) INTO v_candidates;
    END LOOP;
    v_delete_ids := ARRAY[]::text[];
    v_keep := 0;
    FOREACH v_id IN ARRAY COALESCE(v_candidates, ARRAY[]::text[]) LOOP
      v_other := FALSE;
      FOR xref IN
        SELECT * FROM public._cosmas_patient_deletion_exclusive_refs()
         WHERE content_table = v_table
      LOOP
        IF xref.patient_col IS NULL THEN
          v_sql := format(
            'SELECT EXISTS (SELECT 1 FROM public.%I WHERE %I::text = $1)',
            xref.review_table, xref.snapshot_col
          );
          EXECUTE v_sql INTO v_found USING v_id;
        ELSE
          v_sql := format(
            'SELECT EXISTS (SELECT 1 FROM public.%I WHERE %I::text = $1 AND %I IS DISTINCT FROM $2)',
            xref.review_table, xref.snapshot_col, xref.patient_col
          );
          EXECUTE v_sql INTO v_found USING v_id, p_patient;
        END IF;
        IF v_found THEN
          v_other := TRUE;
          EXIT;
        END IF;
      END LOOP;
      IF v_other THEN
        v_keep := v_keep + 1;
      ELSE
        v_delete_ids := array_append(v_delete_ids, v_id);
      END IF;
    END LOOP;
    IF coalesce(array_length(v_delete_ids, 1), 0) > 0 THEN
      v_plan := v_plan || jsonb_build_object(v_table, to_jsonb(v_delete_ids));
      v_counts := v_counts || jsonb_build_object(v_table, array_length(v_delete_ids, 1));
    END IF;
    IF v_keep > 0 THEN
      v_retained := v_retained || jsonb_build_object(v_table, v_keep);
    END IF;
  END LOOP;

  -- patient_links.box_id is runtime-writable; every planned row that carries
  -- box_id must still belong to the patient's practice.
  DECLARE
    v_pbox uuid;
    v_cross boolean;
    v_pkc text[];
  BEGIN
    SELECT pl.box_id INTO v_pbox FROM public.patient_links pl WHERE pl.id = p_patient;
    FOR v_table IN SELECT jsonb_object_keys(v_plan) LOOP
      CONTINUE WHEN NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_attribute a
         WHERE a.attrelid = pg_catalog.format('public.%I', v_table)::regclass
           AND a.attname = 'box_id' AND NOT a.attisdropped
      );
      SELECT array_agg(a.attname ORDER BY k.ord) INTO v_pkc
        FROM pg_catalog.pg_constraint pk
        JOIN unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum
       WHERE pk.conrelid = pg_catalog.format('public.%I', v_table)::regclass
         AND pk.contype = 'p';
      EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM public.%I t WHERE %s = ANY ($1) AND t.box_id IS DISTINCT FROM $2)',
        v_table, public._cosmas_pk_text_expr('t', v_pkc)
      ) INTO v_cross
        USING ARRAY(SELECT jsonb_array_elements_text(v_plan -> v_table)), v_pbox;
      IF v_cross THEN
        RAISE EXCEPTION 'admin authority required';
      END IF;
    END LOOP;
  END;

  -- Refuse ticket/row PKs that collide with a box id or a recording id (except
  -- private_recordings themselves). Local file scans never use ticket ids; this
  -- closes the plan-side bait that inflated dry-run ticket counts.
  DECLARE
    v_collide boolean;
  BEGIN
    FOR v_table IN SELECT jsonb_object_keys(v_plan) LOOP
      CONTINUE WHEN v_table = 'private_recordings';
      SELECT EXISTS (
        SELECT 1
          FROM jsonb_array_elements_text(COALESCE(v_plan -> v_table, '[]'::jsonb)) AS t(id)
         WHERE EXISTS (SELECT 1 FROM public.box_contexts b WHERE b.id::text = t.id)
            OR EXISTS (SELECT 1 FROM public.private_recordings r WHERE r.id::text = t.id)
      ) INTO v_collide;
      IF v_collide THEN
        RAISE EXCEPTION 'admin authority required';
      END IF;
    END LOOP;
  END;

  RETURN jsonb_build_object(
    'tables', v_counts,
    'pks', v_plan,
    'exclusive_retained', v_retained
  );
END
$p$;

CREATE OR REPLACE FUNCTION public.delete_patient_keyed_records_plan(p_patient uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $plan$
DECLARE
  v_built jsonb;
BEGIN
  v_built := public._cosmas_patient_deletion_build_plan(p_patient);
  RETURN jsonb_build_object(
    'tables', COALESCE(v_built -> 'tables', '{}'::jsonb),
    'pks', COALESCE(v_built -> 'pks', '{}'::jsonb),
    'exclusive_retained', COALESCE(v_built -> 'exclusive_retained', '{}'::jsonb),
    'patient_link_id', p_patient::text
  );
END
$plan$;

CREATE OR REPLACE FUNCTION public._cosmas_apply_patient_deletion_mutate(p_patient uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $m$
DECLARE
  v_box uuid;
  v_actor uuid;
  v_owner boolean;
  v_built jsonb;
  v_plan jsonb;
  v_counts jsonb;
  v_table text;
  v_pks text[];
  v_pk_cols text[];
  v_sql text;
  v_pk_expr text;
  v_deleted int;
  v_actual jsonb := '{}'::jsonb;
  v_agg text[];
  rec record;
  v_order text[];
  v_remaining text[];
  v_ready text[];
  v_child text;
  v_parent text;
  v_indeg jsonb := '{}'::jsonb;
  v_edge record;
  v_steps int := 0;
  v_txid bigint := txid_current();
  v_self record;
  v_parent_pk text;
BEGIN
  IF p_patient IS NULL THEN
    RAISE EXCEPTION 'patient records could not be deleted';
  END IF;

  SELECT pl.box_id INTO v_box
    FROM public.patient_links pl
   WHERE pl.id = p_patient
   FOR UPDATE OF pl;
  IF v_box IS NULL THEN
    RAISE EXCEPTION 'patient not found';
  END IF;

  SELECT b.principal_id INTO v_actor
    FROM public.patient_deletion_admin_bindings b
   WHERE b.db_role = session_user
     AND b.box_id = v_box;
  IF v_actor IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  SELECT (p.principal_type = 'human' AND p.state = 'active' AND p.is_owner AND p.box_id = v_box)
    INTO v_owner
    FROM public.principals p WHERE p.id = v_actor;
  IF v_owner IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;

  v_built := public._cosmas_patient_deletion_build_plan(p_patient);
  v_plan := COALESCE(v_built -> 'pks', '{}'::jsonb);
  v_counts := COALESCE(v_built -> 'tables', '{}'::jsonb);

  INSERT INTO public.patient_deletion_in_progress (txid, patient_link_id)
  VALUES (v_txid, p_patient);

  EXECUTE format(
    'SET CONSTRAINTS %I, %I, %I, %I, %I, %I DEFERRED',
    'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
    'fk_ehr_read_request_parent',
    'fk_inbox_current_source',
    'inbox_sources_item_id_box_id_owner_id_fkey',
    'fk_vendor_supersedes_scope',
    'vendor_work_revisions_ticket_id_workspace_id_box_id_owner__fkey'
  );

  -- Aggregate ids for audit scrub: all collected PKs.
  SELECT ARRAY(
    SELECT DISTINCT jsonb_array_elements_text(value)
      FROM jsonb_each(v_plan)
  ) INTO v_agg;
  v_agg := COALESCE(v_agg, ARRAY[]::text[]) || ARRAY[p_patient::text];

  UPDATE public.audit_events ae
     SET aggregate_id = 'redacted', detail = '{}'::jsonb
   WHERE ae.event_type IS DISTINCT FROM 'patient.records_deleted'
     AND ae.box_id = v_box
     AND ae.aggregate_id = ANY (v_agg);

  -- Null self-referential FKs among owned rows first.
  FOR v_self IN
    SELECT child.relname AS table_name,
           (SELECT array_agg(a.attname ORDER BY k.ord)
              FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS child_cols,
           (SELECT array_agg(a.attname ORDER BY k.ord)
              FROM unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum) AS pk_cols,
           (SELECT bool_and(NOT a.attnotnull)
              FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS nullable
      FROM pg_catalog.pg_constraint con
      JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
      JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
      JOIN pg_catalog.pg_constraint pk ON pk.conrelid = child.oid AND pk.contype = 'p'
     WHERE con.contype = 'f'
       AND ns.nspname = 'public'
       AND con.conrelid = con.confrelid
  LOOP
    IF NOT v_self.nullable THEN
      CONTINUE;
    END IF;
    v_pks := ARRAY(SELECT jsonb_array_elements_text(COALESCE(v_plan -> v_self.table_name, '[]'::jsonb)));
    IF coalesce(array_length(v_pks, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    v_pk_expr := public._cosmas_pk_text_expr('t', v_self.pk_cols);
    v_sql := format(
      'UPDATE public.%I t SET %s WHERE %s = ANY ($1)',
      v_self.table_name,
      (SELECT string_agg(format('%I = NULL', col), ', ') FROM unnest(v_self.child_cols) AS col),
      v_pk_expr
    );
    EXECUTE v_sql USING v_pks;
  END LOOP;

  -- Null SHARED/PRESERVE child FKs that point at PATIENT_OWNED rows about to go.
  FOR rec IN
    SELECT child.relname AS child_table,
           parent.relname AS parent_table,
           (SELECT array_agg(a.attname ORDER BY k.ord)
              FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS child_cols,
           (SELECT array_agg(a.attname ORDER BY k.ord)
              FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum) AS parent_cols,
           (SELECT array_agg(a.attname ORDER BY k.ord)
              FROM unnest(ppk.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = ppk.conrelid AND a.attnum = k.attnum) AS parent_pk_cols,
           (SELECT bool_and(NOT a.attnotnull)
              FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
              JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS nullable,
           con.confdeltype AS deltype
      FROM pg_catalog.pg_constraint con
      JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
      JOIN pg_catalog.pg_class parent ON parent.oid = con.confrelid
      JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
      JOIN pg_catalog.pg_namespace pns ON pns.oid = parent.relnamespace
      JOIN pg_catalog.pg_constraint ppk ON ppk.conrelid = parent.oid AND ppk.contype = 'p'
     WHERE con.contype = 'f'
       AND ns.nspname = 'public' AND pns.nspname = 'public'
       AND parent.relname IN (SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind = 'owned')
       AND child.relname IN (SELECT table_name FROM public._cosmas_patient_deletion_classes() WHERE kind IN ('shared', 'preserve'))
  LOOP
    v_pks := ARRAY(SELECT jsonb_array_elements_text(COALESCE(v_plan -> rec.parent_table, '[]'::jsonb)));
    IF coalesce(array_length(v_pks, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    IF rec.deltype = 'n' OR rec.nullable THEN
      v_parent_pk := public._cosmas_pk_text_expr('p', rec.parent_pk_cols);
      v_sql := format(
        'UPDATE public.%I c SET %s FROM public.%I p
          WHERE %s AND %s = ANY ($1)',
        rec.child_table,
        (SELECT string_agg(format('%I = NULL', col), ', ') FROM unnest(rec.child_cols) AS col),
        rec.parent_table,
        (SELECT string_agg(
            format('c.%I IS NOT DISTINCT FROM p.%I', rec.child_cols[ord], rec.parent_cols[ord]),
            ' AND ' ORDER BY ord)
           FROM generate_subscripts(rec.child_cols, 1) AS ord),
        public._cosmas_pk_text_expr('p', rec.parent_pk_cols)
      );
      EXECUTE v_sql USING v_pks;
    END IF;
  END LOOP;

  -- Topological delete order among owned tables that have rows (ignore declared cycle edges).
  SELECT ARRAY(SELECT DISTINCT jsonb_object_keys(v_plan)) INTO v_remaining;
  v_remaining := COALESCE(v_remaining, ARRAY[]::text[]);
  FOR v_table IN SELECT * FROM unnest(v_remaining) LOOP
    v_indeg := v_indeg || jsonb_build_object(v_table, 0);
  END LOOP;
  FOR v_edge IN
    SELECT child.relname AS c, parent.relname AS p, con.conname AS n
      FROM pg_catalog.pg_constraint con
      JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
      JOIN pg_catalog.pg_class parent ON parent.oid = con.confrelid
      JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
      JOIN pg_catalog.pg_namespace pns ON pns.oid = parent.relnamespace
     WHERE con.contype = 'f'
       AND ns.nspname = 'public' AND pns.nspname = 'public'
       AND child.relname = ANY (v_remaining)
       AND parent.relname = ANY (v_remaining)
       AND child.relname <> parent.relname
       AND con.conname <> ALL (ARRAY[
         'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
         'fk_ehr_read_request_parent',
         'fk_inbox_current_source',
         'inbox_sources_item_id_box_id_owner_id_fkey',
         'fk_vendor_supersedes_scope',
         'vendor_work_revisions_ticket_id_workspace_id_box_id_owner__fkey'
       ])
  LOOP
    -- edge child depends on parent: indegree of parent increases (delete child first)
    v_indeg := v_indeg || jsonb_build_object(
      v_edge.p,
      COALESCE((v_indeg ->> v_edge.p)::int, 0) + 1
    );
  END LOOP;

  v_order := ARRAY[]::text[];
  LOOP
    v_steps := v_steps + 1;
    IF v_steps > 10000 THEN
      RAISE EXCEPTION 'patient records could not be deleted';
    END IF;
    SELECT ARRAY(
      SELECT t FROM unnest(v_remaining) AS t
       WHERE COALESCE((v_indeg ->> t)::int, 0) = 0
       ORDER BY t
    ) INTO v_ready;
    EXIT WHEN coalesce(array_length(v_ready, 1), 0) = 0;
    v_table := v_ready[1];
    v_order := array_append(v_order, v_table);
    v_remaining := array_remove(v_remaining, v_table);
    FOR v_edge IN
      SELECT child.relname AS c, parent.relname AS p, con.conname AS n
        FROM pg_catalog.pg_constraint con
        JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
        JOIN pg_catalog.pg_class parent ON parent.oid = con.confrelid
        JOIN pg_catalog.pg_namespace ns ON ns.oid = child.relnamespace
        JOIN pg_catalog.pg_namespace pns ON pns.oid = parent.relnamespace
       WHERE con.contype = 'f'
         AND ns.nspname = 'public' AND pns.nspname = 'public'
         AND child.relname = v_table
         AND parent.relname = ANY (v_remaining)
         AND child.relname <> parent.relname
         AND con.conname <> ALL (ARRAY[
           'ehr_read_snapshots_observation_id_box_id_owner_id_fkey',
           'fk_ehr_read_request_parent',
           'fk_inbox_current_source',
           'inbox_sources_item_id_box_id_owner_id_fkey',
           'fk_vendor_supersedes_scope',
           'vendor_work_revisions_ticket_id_workspace_id_box_id_owner__fkey'
         ])
    LOOP
      v_indeg := v_indeg || jsonb_build_object(
        v_edge.p,
        GREATEST(COALESCE((v_indeg ->> v_edge.p)::int, 0) - 1, 0)
      );
    END LOOP;
  END LOOP;
  -- leftover cycle members (declared): append sorted
  IF coalesce(array_length(v_remaining, 1), 0) > 0 THEN
    v_order := v_order || ARRAY(SELECT * FROM unnest(v_remaining) ORDER BY 1);
  END IF;

  FOREACH v_table IN ARRAY v_order LOOP
    v_pks := ARRAY(SELECT jsonb_array_elements_text(COALESCE(v_plan -> v_table, '[]'::jsonb)));
    IF coalesce(array_length(v_pks, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    SELECT array_agg(a.attname ORDER BY k.ord)
      INTO v_pk_cols
      FROM pg_catalog.pg_constraint pk
      JOIN pg_catalog.pg_class c ON c.oid = pk.conrelid
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      JOIN unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
      JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum
     WHERE pk.contype = 'p' AND n.nspname = 'public' AND c.relname = v_table;
    v_pk_expr := public._cosmas_pk_text_expr('t', v_pk_cols);
    v_sql := format('DELETE FROM public.%I t WHERE %s = ANY ($1)', v_table, v_pk_expr);
    EXECUTE v_sql USING v_pks;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    IF v_deleted > 0 THEN
      v_actual := v_actual || jsonb_build_object(v_table, v_deleted);
    END IF;
  END LOOP;

  INSERT INTO public.audit_events (
    id, box_id, aggregate_type, aggregate_id, event_type,
    actor_principal_id, outcome, detail, created_at
  ) VALUES (
    gen_random_uuid(), v_box, 'patient_link', p_patient::text,
    'patient.records_deleted', v_actor, 'deleted', '{}'::jsonb, now()
  );

  DELETE FROM public.patient_deletion_in_progress WHERE txid = v_txid;

  RETURN jsonb_build_object(
    'tables', v_actual,
    'exclusive_retained', COALESCE(v_built -> 'exclusive_retained', '{}'::jsonb),
    'patient_link_id', p_patient::text,
    'actor_principal_id', v_actor::text
  );
EXCEPTION WHEN OTHERS THEN
  DELETE FROM public.patient_deletion_in_progress WHERE txid = v_txid;
  RAISE;
END
$m$;

CREATE OR REPLACE FUNCTION public.delete_patient_keyed_records(p_patient uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $d$
BEGIN
  RETURN public._cosmas_apply_patient_deletion_mutate(p_patient);
END
$d$;

-- Admin LOGIN needs only membership + EXECUTE on these helpers (L1).

CREATE OR REPLACE FUNCTION public.patient_deletion_resolve_admin()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $r$
DECLARE
  v_principal uuid;
  v_box uuid;
  v_ok boolean;
BEGIN
  IF NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  SELECT b.principal_id, b.box_id INTO v_principal, v_box
    FROM public.patient_deletion_admin_bindings b
   WHERE b.db_role = session_user;
  IF v_principal IS NULL OR v_box IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  SELECT (p.principal_type = 'human' AND p.state = 'active' AND p.is_owner AND p.box_id = v_box)
    INTO v_ok
    FROM public.principals p WHERE p.id = v_principal;
  IF v_ok IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  RETURN jsonb_build_object(
    'principal_id', v_principal::text,
    'box_id', v_box::text
  );
END
$r$;

CREATE OR REPLACE FUNCTION public.patient_deletion_collect_file_keys(p_pks jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $c$
DECLARE
  v_out jsonb := '[]'::jsonb;
  v_table text;
  v_values text[];
  v_pk_cols text[];
  v_file_cols text[];
  v_pk_expr text;
  v_sql text;
  v_kind text;
  v_path text;
  v_col text;
  v_box text;
  v_workspace text;
  v_owner text;
  v_artifact text;
  v_caller_box uuid;
  v_has_box boolean;
  v_has_patient boolean;
  v_rowpk text;
BEGIN
  IF p_pks IS NULL OR jsonb_typeof(p_pks) <> 'object' THEN
    RETURN '[]'::jsonb;
  END IF;
  -- Deletion-role callers are limited to their bound practice; runtime dry-run
  -- (non-member) keeps the PK set from the plan and is practice-checked in app code.
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'cosmas_patient_deletion')
     AND pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    SELECT b.box_id INTO v_caller_box
      FROM public.patient_deletion_admin_bindings b
     WHERE b.db_role = session_user;
    IF v_caller_box IS NULL THEN
      RAISE EXCEPTION 'admin authority required';
    END IF;
  END IF;
  FOR v_table IN SELECT jsonb_object_keys(p_pks) ORDER BY 1 LOOP
    SELECT ARRAY(SELECT jsonb_array_elements_text(COALESCE(p_pks -> v_table, '[]'::jsonb)))
      INTO v_values;
    IF coalesce(array_length(v_values, 1), 0) = 0 THEN
      CONTINUE;
    END IF;
    SELECT array_agg(a.attname ORDER BY k.ord)
      INTO v_pk_cols
      FROM pg_catalog.pg_constraint pk
      JOIN pg_catalog.pg_class c ON c.oid = pk.conrelid
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      JOIN unnest(pk.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
      JOIN pg_catalog.pg_attribute a ON a.attrelid = pk.conrelid AND a.attnum = k.attnum
     WHERE pk.contype = 'p' AND n.nspname = 'public' AND c.relname = v_table;
    IF v_pk_cols IS NULL THEN
      CONTINUE;
    END IF;
    v_pk_expr := public._cosmas_pk_text_expr('t', v_pk_cols);
    IF v_caller_box IS NOT NULL THEN
      SELECT EXISTS (
               SELECT 1 FROM pg_catalog.pg_attribute a
                 JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                 JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = v_table
                  AND NOT a.attisdropped AND a.attnum > 0 AND a.attname = 'box_id'
             ),
             EXISTS (
               SELECT 1 FROM pg_catalog.pg_attribute a
                 JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                 JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = v_table
                  AND NOT a.attisdropped AND a.attnum > 0 AND a.attname = 'patient_link_id'
             )
        INTO v_has_box, v_has_patient;
      IF v_has_box THEN
        v_sql := format(
          'SELECT ARRAY(SELECT %s FROM public.%I t WHERE %s = ANY ($1) AND t.box_id = $2)',
          v_pk_expr, v_table, v_pk_expr
        );
        EXECUTE v_sql INTO v_values USING v_values, v_caller_box;
      ELSIF v_has_patient THEN
        v_sql := format(
          'SELECT ARRAY(
             SELECT %s FROM public.%I t
              JOIN public.patient_links pl ON pl.id = t.patient_link_id
              WHERE %s = ANY ($1) AND pl.box_id = $2
           )',
          v_pk_expr, v_table, v_pk_expr
        );
        EXECUTE v_sql INTO v_values USING v_values, v_caller_box;
      ELSIF v_table = 'patient_links' THEN
        v_sql := format(
          'SELECT ARRAY(SELECT %s FROM public.%I t WHERE %s = ANY ($1) AND t.box_id = $2)',
          v_pk_expr, v_table, v_pk_expr
        );
        EXECUTE v_sql INTO v_values USING v_values, v_caller_box;
      END IF;
      -- Tables without a practice key cannot contribute cross-practice file
      -- paths here; file-column / vendor_artifacts loops below still run only
      -- on the (possibly filtered) PK set from the patient plan.
      IF coalesce(array_length(v_values, 1), 0) = 0 THEN
        CONTINUE;
      END IF;
    END IF;
    SELECT array_agg(a.attname ORDER BY a.attname)
      INTO v_file_cols
      FROM pg_catalog.pg_attribute a
      JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = v_table
       AND NOT a.attisdropped AND a.attnum > 0
       AND a.attname = ANY (ARRAY[
         'blob_key','file_key','storage_key','object_key',
         'audio_key','audio_path','export_key','export_path'
       ]);
    IF coalesce(array_length(v_file_cols, 1), 0) > 0 THEN
      FOREACH v_col IN ARRAY v_file_cols LOOP
        v_kind := CASE
          WHEN v_col IN ('audio_key', 'audio_path') THEN 'audio'
          WHEN v_col IN ('export_key', 'export_path') THEN 'exports'
          ELSE 'uploads'
        END;
        v_sql := format(
          'SELECT t.%I::text, %s FROM public.%I t WHERE %s = ANY ($1) AND t.%I IS NOT NULL',
          v_col, v_pk_expr, v_table, v_pk_expr, v_col
        );
        FOR v_path, v_rowpk IN EXECUTE v_sql USING v_values LOOP
          IF v_path IS NULL OR v_path = '' OR position('/' in v_path) = 1
             OR position('..' in v_path) > 0 THEN
            CONTINUE;
          END IF;
          -- Key columns are runtime-writable: only trust a key that names its own
          -- row ({box}/{id}/... or {box}/.../{id}.ext) inside the caller's practice.
          IF NOT (v_rowpk = ANY (string_to_array(regexp_replace(v_path, '\.[^/]*$', ''), '/'))) THEN
            CONTINUE;
          END IF;
          IF v_caller_box IS NOT NULL
             AND split_part(v_path, '/', 1) IS DISTINCT FROM v_caller_box::text THEN
            CONTINUE;
          END IF;
          v_out := v_out || jsonb_build_array(
            jsonb_build_object('kind', v_kind, 'path', v_path)
          );
        END LOOP;
      END LOOP;
    END IF;
    IF v_table = 'vendor_artifacts' THEN
      v_sql := format(
        'SELECT t.box_id::text, t.workspace_id::text, t.owner_id::text, t.artifact_id::text
           FROM public.vendor_artifacts t WHERE %s = ANY ($1)',
        v_pk_expr
      );
      FOR v_box, v_workspace, v_owner, v_artifact IN EXECUTE v_sql USING v_values LOOP
        IF v_caller_box IS NOT NULL AND v_box IS DISTINCT FROM v_caller_box::text THEN
          CONTINUE;
        END IF;
        v_path := v_box || '/vendor-documents/' || v_workspace || '/' || v_owner
                  || '/' || v_artifact || '.pdf';
        v_out := v_out || jsonb_build_array(
          jsonb_build_object('kind', 'exports', 'path', v_path)
        );
      END LOOP;
    END IF;
  END LOOP;
  RETURN v_out;
END
$c$;

CREATE OR REPLACE FUNCTION public.patient_deletion_pending_list(p_box uuid)
RETURNS TABLE(id uuid, kind text, relative_path text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $l$
BEGIN
  IF p_box IS NULL OR NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  -- Owner/admin only (R2b): staff- and agent-bound logins cannot touch pending rows.
  IF NOT EXISTS (
    SELECT 1
      FROM public.patient_deletion_admin_bindings b
      JOIN public.principals p ON p.id = b.principal_id
     WHERE b.db_role = session_user
       AND b.box_id = p_box
       AND p.principal_type = 'human'
       AND p.state = 'active'
       AND p.is_owner
       AND p.box_id = p_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  -- Patient may already be gone on rerun. Keep rows whose living patient (if
  -- any) still belongs to this box; drop forged rows that name another practice.
  RETURN QUERY
    SELECT f.id, f.kind::text, f.relative_path::text
      FROM public.patient_deletion_pending_files f
     WHERE f.box_id = p_box
       AND NOT EXISTS (
         SELECT 1 FROM public.patient_links pl
          WHERE pl.id = f.patient_link_id
            AND pl.box_id IS DISTINCT FROM p_box
       )
       AND (
         f.relative_path !~ '^[0-9a-fA-F-]{36}/vendor-documents/'
         OR split_part(f.relative_path, '/', 1) = p_box::text
       )
     ORDER BY f.created_at, f.id
     FOR UPDATE OF f;
END
$l$;

CREATE OR REPLACE FUNCTION public.patient_deletion_pending_record(
  p_patient uuid, p_box uuid, p_files jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $rec$
DECLARE
  item jsonb;
  v_path text;
  v_kind text;
  v_ids text[];
  v_segs text[];
BEGIN
  IF p_patient IS NULL OR p_box IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM public.patient_deletion_admin_bindings b
      JOIN public.principals p ON p.id = b.principal_id
     WHERE b.db_role = session_user
       AND b.box_id = p_box
       AND p.principal_type = 'human'
       AND p.state = 'active'
       AND p.is_owner
       AND p.box_id = p_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.patient_links pl
     WHERE pl.id = p_patient AND pl.box_id = p_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF p_files IS NULL OR jsonb_typeof(p_files) <> 'array' THEN
    RETURN;
  END IF;
  v_ids := ARRAY(
    SELECT jsonb_array_elements_text(value)
      FROM jsonb_each(public._cosmas_patient_deletion_build_plan(p_patient) -> 'pks')
  ) || ARRAY[p_patient::text];
  FOR item IN SELECT * FROM jsonb_array_elements(p_files) LOOP
    v_path := coalesce(item ->> 'path', '');
    v_kind := coalesce(item ->> 'kind', '');
    IF v_path = '' OR v_kind = '' THEN
      CONTINUE;
    END IF;
    IF position('/' in v_path) = 1 OR position('..' in v_path) > 0 THEN
      RAISE EXCEPTION 'admin authority required';
    END IF;
    -- Same rule as the file scan: the path must name one of this patient's
    -- planned rows, and a path rooted at a practice must be rooted at p_box.
    v_segs := string_to_array(regexp_replace(v_path, '\.[^/]*$', ''), '/');
    IF NOT (v_segs && v_ids)
       OR (split_part(v_path, '/', 1) ~ '^[0-9a-fA-F-]{36}$'
           AND split_part(v_path, '/', 1) <> p_box::text
           AND NOT (split_part(v_path, '/', 1) = ANY (v_ids))) THEN
      RAISE EXCEPTION 'admin authority required';
    END IF;
    INSERT INTO public.patient_deletion_pending_files (
      patient_link_id, box_id, kind, relative_path
    ) VALUES (
      p_patient, p_box, v_kind, v_path
    );
  END LOOP;
END
$rec$;

CREATE OR REPLACE FUNCTION public.patient_deletion_pending_clear(
  p_patient uuid, p_paths text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $clr$
DECLARE
  v_box uuid;
BEGIN
  IF p_patient IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  SELECT b.box_id INTO v_box
    FROM public.patient_deletion_admin_bindings b
    JOIN public.principals p ON p.id = b.principal_id
   WHERE b.db_role = session_user
     AND p.principal_type = 'human'
     AND p.state = 'active'
     AND p.is_owner
     AND p.box_id = b.box_id;
  IF v_box IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  -- Refuse clearing another practice's patient or pending rows. Patient rows
  -- may already be gone after mutate; then only same-box pending rows clear.
  IF EXISTS (
    SELECT 1 FROM public.patient_links pl
     WHERE pl.id = p_patient AND pl.box_id IS DISTINCT FROM v_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.patient_deletion_pending_files f
     WHERE f.patient_link_id = p_patient
       AND f.box_id IS DISTINCT FROM v_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF coalesce(array_length(p_paths, 1), 0) = 0 THEN
    DELETE FROM public.patient_deletion_pending_files f
     WHERE f.patient_link_id = p_patient
       AND f.box_id = v_box
       AND (
         f.relative_path !~ '^[0-9a-fA-F-]{36}/vendor-documents/'
         OR split_part(f.relative_path, '/', 1) = v_box::text
       );
  ELSE
    IF EXISTS (
      SELECT 1 FROM unnest(p_paths) AS p(path)
       WHERE p.path ~ '^[0-9a-fA-F-]{36}/vendor-documents/'
         AND split_part(p.path, '/', 1) IS DISTINCT FROM v_box::text
    ) THEN
      RAISE EXCEPTION 'admin authority required';
    END IF;
    DELETE FROM public.patient_deletion_pending_files f
     WHERE f.patient_link_id = p_patient
       AND f.box_id = v_box
       AND f.relative_path = ANY (p_paths);
  END IF;
END
$clr$;

CREATE OR REPLACE FUNCTION public.patient_deletion_pending_delete(p_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $del$
DECLARE
  v_box uuid;
  v_patient uuid;
  v_path text;
BEGIN
  IF p_id IS NULL THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF NOT pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  SELECT f.box_id, f.patient_link_id, f.relative_path
    INTO v_box, v_patient, v_path
    FROM public.patient_deletion_pending_files f
   WHERE f.id = p_id
   FOR UPDATE OF f;
  IF v_box IS NULL THEN
    RETURN;
  END IF;
  IF NOT EXISTS (
    SELECT 1
      FROM public.patient_deletion_admin_bindings b
      JOIN public.principals p ON p.id = b.principal_id
     WHERE b.db_role = session_user
       AND b.box_id = v_box
       AND p.principal_type = 'human'
       AND p.state = 'active'
       AND p.is_owner
       AND p.box_id = v_box
  ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  -- Patient may already be gone on rerun; if the link remains it must match box.
  IF EXISTS (SELECT 1 FROM public.patient_links pl WHERE pl.id = v_patient)
     AND NOT EXISTS (
       SELECT 1 FROM public.patient_links pl
        WHERE pl.id = v_patient AND pl.box_id = v_box
     ) THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  IF v_path ~ '^[0-9a-fA-F-]{36}/vendor-documents/'
     AND split_part(v_path, '/', 1) IS DISTINCT FROM v_box::text THEN
    RAISE EXCEPTION 'admin authority required';
  END IF;
  DELETE FROM public.patient_deletion_pending_files WHERE id = p_id;
END
$del$;

CREATE OR REPLACE FUNCTION public.patient_deletion_patient_box(p_patient uuid)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $b$
DECLARE
  v_box text;
BEGIN
  IF p_patient IS NULL THEN
    RAISE EXCEPTION 'patient not found';
  END IF;
  SELECT pl.box_id::text INTO v_box FROM public.patient_links pl WHERE pl.id = p_patient;
  IF v_box IS NULL THEN
    RAISE EXCEPTION 'patient not found';
  END IF;
  -- Deletion-role callers may only resolve patients in their bound practice.
  -- Runtime dry-run (non-member) is practice-checked in application code.
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'cosmas_patient_deletion')
     AND pg_has_role(session_user, 'cosmas_patient_deletion', 'MEMBER') THEN
    IF NOT EXISTS (
      SELECT 1 FROM public.patient_deletion_admin_bindings b
       WHERE b.db_role = session_user AND b.box_id = v_box::uuid
    ) THEN
      RAISE EXCEPTION 'admin authority required';
    END IF;
  END IF;
  RETURN v_box;
END
$b$;
