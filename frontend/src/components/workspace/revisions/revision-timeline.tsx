export type RevisionTimelineItem = {
  revisionId: string;
  label: string;
  status: string;
};

type RevisionTimelineProps = {
  revisions: RevisionTimelineItem[];
  activeRevisionId?: string;
};

export function RevisionTimeline({
  revisions,
  activeRevisionId,
}: RevisionTimelineProps) {
  const activeRevision = revisions.find(
    (revision) => revision.revisionId === activeRevisionId,
  );

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Revisions</h2>
      <div data-testid="revision-timeline" className="space-y-2">
        {activeRevision ? (
          <div
            data-testid="active-revision-badge"
            className="inline-flex rounded-md border px-2 py-1 text-xs"
          >
            Active: {activeRevision.label}
          </div>
        ) : null}
        {revisions.length === 0 ? (
          <p className="text-muted-foreground text-xs">No revisions yet.</p>
        ) : (
          revisions.map((revision) => (
            <div
              key={revision.revisionId}
              className="rounded-md border px-2 py-1 text-xs"
            >
              <div className="font-medium">{revision.label}</div>
              <div className="text-muted-foreground">{revision.status}</div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}