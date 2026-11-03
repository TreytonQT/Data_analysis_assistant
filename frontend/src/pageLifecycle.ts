/** Shared contract for pages retained by the application's navigation shell. */
export interface PageLifecycleProps {
  active?: boolean;
  routeVersion?: number;
  refreshVersion?: number;
}
