import { useRef, useState } from "preact/hooks";
import { CopyButton, StatusPill } from "../components/ui";
import {
  generatePythonTask,
  pythonTaskDraftKey,
  pythonTaskGenerationCanApply,
  requestPythonTaskRun,
  schedulePythonTask,
  stagePythonTask,
  testPythonTask,
  validatePythonTask,
  type PythonTaskCapability,
  type PythonTaskDraft,
  type PythonTaskFileDraft,
  type PythonTaskPlanResponse,
  type PythonTaskRunRequestResponse,
  type PythonTaskScheduleResponse,
  type PythonTaskValidation,
} from "../workflow/python-task";
import {
  identityForMutationIntent,
  type MutationIntentIdentity,
} from "../mutation-intent";

const CAPABILITIES: readonly PythonTaskCapability[] = [
  "gpu",
  "network",
  "filesystem_read",
  "filesystem_write",
];

const INITIAL_FILES: readonly PythonTaskFileDraft[] = [{
  path: "main.py",
  content: [
    "import json",
    "import torch",
    "",
    "result = {",
    "    \"cuda_available\": torch.cuda.is_available(),",
    "    \"device_count\": torch.cuda.device_count(),",
    "}",
    "print(json.dumps(result, sort_keys=True))",
    "",
  ].join("\n"),
}];

type Result = PythonTaskValidation | PythonTaskPlanResponse | PythonTaskRunRequestResponse | PythonTaskScheduleResponse;

interface StagedArtifact {
  readonly ref: string;
  readonly draftKey: string;
}

export function PythonTaskWorkbench({ onBack }: { readonly onBack: () => void }) {
  const governedRunIntent = useRef<MutationIntentIdentity | null>(null);
  const draftRevision = useRef(0);
  const [files, setFiles] = useState<readonly PythonTaskFileDraft[]>(INITIAL_FILES);
  const [intent, setIntent] = useState("Write a Python task that reports CUDA availability and GPU count as JSON.");
  const [selectedPath, setSelectedPath] = useState("main.py");
  const [newPath, setNewPath] = useState("");
  const [taskId, setTaskId] = useState("gpu.health-check");
  const [version, setVersion] = useState("1.0.0");
  const [entrypoint, setEntrypoint] = useState("main.py");
  const [modules, setModules] = useState("torch");
  const [capabilities, setCapabilities] = useState<readonly PythonTaskCapability[]>(["gpu"]);
  const [timeoutSeconds, setTimeoutSeconds] = useState(300);
  const [target, setTarget] = useState("resource:compute/vm/gpu-worker");
  const [reason, setReason] = useState("Run the validated GPU health task.");
  const [cronExpression, setCronExpression] = useState("0 2 * * *");
  const [stagedArtifact, setStagedArtifact] = useState<StagedArtifact | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = files.find((file) => file.path === selectedPath) ?? files[0];

  const draft = (): PythonTaskDraft => ({
    task_id: taskId.trim(),
    version: version.trim(),
    entrypoint: entrypoint.trim(),
    files,
    required_modules: modules.split(",").map((value) => value.trim()).filter(Boolean),
    capabilities,
    timeout_seconds: timeoutSeconds,
    python_executable: "/usr/bin/python3",
  });
  const artifactRef = stagedArtifact?.draftKey === pythonTaskDraftKey(draft())
    ? stagedArtifact.ref
    : null;

  const run = async (
    action: string,
    operation: () => Promise<Result>,
    stagedDraftKey?: string,
  ) => {
    setBusy(action);
    setError(null);
    try {
      const next = await operation();
      setResult(next);
      if (
        "staged" in next
        && next.staged === true
        && typeof next.artifact_ref === "string"
        && stagedDraftKey !== undefined
      ) {
        setStagedArtifact({ ref: next.artifact_ref, draftKey: stagedDraftKey });
      }
      if ("submitted" in next && next.submitted) governedRunIntent.current = null;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  const updateSelected = (content: string) => {
    draftRevision.current += 1;
    setFiles(files.map((file) => file.path === selected?.path ? { ...file, content } : file));
    setStagedArtifact(null);
  };

  const addFile = () => {
    const path = newPath.trim();
    if (!path || files.some((file) => file.path === path)) return;
    draftRevision.current += 1;
    setFiles([...files, { path, content: "" }]);
    setSelectedPath(path);
    setNewPath("");
    setStagedArtifact(null);
  };

  const removeSelected = () => {
    if (!selected || files.length === 1) return;
    draftRevision.current += 1;
    const remaining = files.filter((file) => file.path !== selected.path);
    setFiles(remaining);
    setSelectedPath(remaining[0]?.path ?? "");
    if (entrypoint === selected.path) setEntrypoint(remaining[0]?.path ?? "");
    setStagedArtifact(null);
  };

  const generate = async () => {
    const submittedRevision = draftRevision.current;
    setBusy("generate");
    setError(null);
    try {
      const generated = await generatePythonTask({
        intent: intent.trim(),
        taskIdHint: taskId.trim(),
        targetResourceRef: target.trim(),
        allowedModules: modules.split(",").map((value) => value.trim()).filter(Boolean),
      });
      if (!pythonTaskGenerationCanApply(draftRevision.current, submittedRevision)) {
        setError("Generated draft was discarded because the task changed while authoring.");
        return;
      }
      const task = generated.task;
      draftRevision.current += 1;
      setFiles(task.files);
      setSelectedPath(task.entrypoint);
      setTaskId(task.task_id);
      setVersion(task.version);
      setEntrypoint(task.entrypoint);
      setModules(task.required_modules.join(","));
      setCapabilities(task.capabilities);
      setTimeoutSeconds(task.timeout_seconds);
      setStagedArtifact(null);
      setResult(generated.validation);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section class="python-task-workbench">
      <header class="python-task-head">
        <div>
          <span class="eyebrow">Ontology action / tool.run-python-on-vm</span>
          <h3>Python VM task</h3>
        </div>
        <button type="button" class="btn btn-small" onClick={onBack}>Back to workflows</button>
      </header>

      <div class="python-task-layout">
        <section class="python-task-editor" aria-label="Task source files">
          <div class="python-task-filebar">
            <div class="python-task-tabs">
              {files.map((file) => (
                <button
                  key={file.path}
                  type="button"
                  class={file.path === selected?.path ? "is-active" : ""}
                  onClick={() => setSelectedPath(file.path)}
                >
                  {file.path}
                </button>
              ))}
            </div>
            <button type="button" class="btn btn-small" onClick={removeSelected} disabled={files.length === 1} aria-label="Remove selected file">Remove</button>
          </div>
          <textarea
            class="python-task-code mono"
            aria-label={`Source for ${selected?.path ?? "task file"}`}
            value={selected?.content ?? ""}
            spellcheck={false}
            onInput={(event) => updateSelected((event.target as HTMLTextAreaElement).value)}
          />
          <div class="python-task-add-file">
            <input value={newPath} placeholder="helpers.py" aria-label="New file path" onInput={(event) => setNewPath((event.target as HTMLInputElement).value)} />
            <button type="button" class="btn btn-small" onClick={addFile}>Add file</button>
          </div>
        </section>

        <aside class="python-task-manifest" aria-label="Task manifest">
          <label><span>Task id</span><input value={taskId} onInput={(event) => { draftRevision.current += 1; setTaskId((event.target as HTMLInputElement).value); setStagedArtifact(null); }} /></label>
          <label><span>Version</span><input value={version} onInput={(event) => { draftRevision.current += 1; setVersion((event.target as HTMLInputElement).value); setStagedArtifact(null); }} /></label>
          <label><span>Entrypoint</span><select value={entrypoint} onChange={(event) => { draftRevision.current += 1; setEntrypoint((event.target as HTMLSelectElement).value); }}>{files.filter((file) => file.path.endsWith(".py")).map((file) => <option key={file.path} value={file.path}>{file.path}</option>)}</select></label>
          <label><span>Required modules</span><input value={modules} placeholder="torch,numpy" onInput={(event) => { draftRevision.current += 1; setModules((event.target as HTMLInputElement).value); }} /></label>
          <label><span>Timeout seconds</span><input type="number" min="1" max="86400" value={timeoutSeconds} onInput={(event) => { draftRevision.current += 1; setTimeoutSeconds(Number((event.target as HTMLInputElement).value)); }} /></label>
          <fieldset>
            <legend>Capabilities</legend>
            {CAPABILITIES.map((capability) => <label key={capability} class="python-task-check"><input type="checkbox" checked={capabilities.includes(capability)} onChange={() => { draftRevision.current += 1; setCapabilities(capabilities.includes(capability) ? capabilities.filter((value) => value !== capability) : [...capabilities, capability]); }} /><span>{capability.replaceAll("_", " ")}</span></label>)}
          </fieldset>
          <label><span>Target Resource</span><input value={target} onInput={(event) => setTarget((event.target as HTMLInputElement).value)} /></label>
          <label><span>Run reason</span><textarea value={reason} rows={3} onInput={(event) => setReason((event.target as HTMLTextAreaElement).value)} /></label>
          <label><span>Cron schedule</span><input value={cronExpression} onInput={(event) => setCronExpression((event.target as HTMLInputElement).value)} /></label>
        </aside>
      </div>

      <div class="python-task-intent">
        <label><span>Task intent</span><textarea value={intent} rows={2} onInput={(event) => setIntent((event.target as HTMLTextAreaElement).value)} /></label>
        <button type="button" class="btn" disabled={busy !== null || !intent.trim()} onClick={() => void generate()}>{busy === "generate" ? "Authoring..." : "Generate editable draft"}</button>
      </div>

      <div class="python-task-actions">
        <button type="button" class="btn" disabled={busy !== null} onClick={() => void run("validate", () => validatePythonTask(draft()))}>{busy === "validate" ? "Validating..." : "Validate"}</button>
        <button type="button" class="btn" disabled={busy !== null} onClick={() => { const task = draft(); void run("stage", () => stagePythonTask(task), pythonTaskDraftKey(task)); }}>{busy === "stage" ? "Staging..." : "Stage artifact"}</button>
        <button type="button" class="btn" disabled={busy !== null || !target.trim()} onClick={() => void run("test", () => testPythonTask(draft(), target.trim()))}>{busy === "test" ? "Testing..." : "Test shadow plan"}</button>
        <button type="button" class="btn primary" disabled={busy !== null || artifactRef === null || reason.trim().length < 10} onClick={() => { const request = { artifactRef: artifactRef ?? "", targetResourceRef: target.trim(), reason: reason.trim() }; const identity = identityForMutationIntent(governedRunIntent.current, JSON.stringify(request)); governedRunIntent.current = identity; void run("request", () => requestPythonTaskRun({ ...request, idempotencyKey: identity.idempotencyKey })); }}>{busy === "request" ? "Submitting..." : "Request governed run"}</button>
        <button type="button" class="btn" disabled={busy !== null || artifactRef === null || !cronExpression.trim()} onClick={() => void run("schedule", () => schedulePythonTask({ artifactRef: artifactRef ?? "", targetResourceRef: target.trim(), workflowRef: "scheduled-gpu-python-task", cronExpression: cronExpression.trim() }))}>{busy === "schedule" ? "Scheduling..." : "Create schedule"}</button>
      </div>

      <PythonTaskResult result={result} error={error} artifactRef={artifactRef} />
    </section>
  );
}

function PythonTaskResult({ result, error, artifactRef }: { readonly result: Result | null; readonly error: string | null; readonly artifactRef: string | null }) {
  if (error) return <div class="state-block state-error" role="alert"><span class="state-icon">!</span><span>{error}</span></div>;
  if (!result) return <div class="python-task-result muted">No validation or run result yet.</div>;
  if ("submitted" in result) {
    return <div class="python-task-result"><div><StatusPill kind="hil" label="submitted for judgment" /><strong>{result.action_type}</strong></div><dl><div><dt>Correlation</dt><dd class="mono">{result.correlation_id}</dd></div><div><dt>Target</dt><dd class="mono">{result.target_resource_ref}</dd></div></dl></div>;
  }
  if ("scheduled" in result) {
    return <div class="python-task-result"><div><StatusPill kind="success" label="scheduled" /><strong>{result.workflow_ref}</strong></div><dl><div><dt>Task</dt><dd class="mono">{result.task_id}</dd></div><div><dt>Cron</dt><dd class="mono">{result.cron_expression}</dd></div><div><dt>Event</dt><dd class="mono">{result.event_type}</dd></div><div><dt>Target</dt><dd class="mono">{result.target_resource_ref}</dd></div></dl></div>;
  }
  const plan = "plan" in result ? result.plan : null;
  return <div class="python-task-result"><div><StatusPill kind={result.valid ? "success" : "danger"} label={result.valid ? "valid" : "blocked"} />{artifactRef ? <CopyButton text={artifactRef} label="Copy artifact ref" /> : null}</div>{result.issues.length > 0 ? <ul>{result.issues.map((issue) => <li key={`${issue.code}:${issue.path}`}><strong>{issue.code}</strong> <span class="mono">{issue.path}</span> - {issue.message}</li>)}</ul> : null}{plan ? <dl><div><dt>Status</dt><dd>{plan.status}</dd></div><div><dt>Files</dt><dd>{plan.files_would_copy}</dd></div><div><dt>Bytes</dt><dd>{plan.bytes_would_copy}</dd></div><div><dt>Target capabilities</dt><dd>{plan.target_capabilities.join(", ")}</dd></div></dl> : null}</div>;
}
