export type RevisionActionResponse = {
  revision_id: string;
  status?: string;
};

export type SwitchActiveRevisionRequest = {
  revision_id: string;
};