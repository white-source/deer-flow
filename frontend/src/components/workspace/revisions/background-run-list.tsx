export type BackgroundRunItem = {
  runId: string;
  label: string;
  status: string;
};

type BackgroundRunListProps = {
  runs: BackgroundRunItem[];
};

export function BackgroundRunList({ runs }: BackgroundRunListProps) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Background Runs</h2>
      {runs.length === 0 ? (
        <p className="text-muted-foreground text-xs">No background runs.</p>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <div key={run.runId} className="rounded-md border px-2 py-1 text-xs">
              <div className="font-medium">{run.label}</div>
              <div className="text-muted-foreground">{run.status}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}