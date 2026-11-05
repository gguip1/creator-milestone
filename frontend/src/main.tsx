import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import "./index.css";
import { ClientPage } from "./pages/Client";
import { IntakePage } from "./pages/Intake";
import { Landing } from "./pages/Landing";
import { NewMessagePage } from "./pages/NewMessage";
import { ProjectPage } from "./pages/Project";
import { SettingsPage } from "./pages/Settings";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true }, mutations: { retry: false } },
});

const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/projects/:id", element: <ProjectPage /> },
  { path: "/projects/:id/intake", element: <IntakePage /> },
  { path: "/projects/:id/messages/new", element: <NewMessagePage /> },
  { path: "/c/:token", element: <ClientPage /> },
  { path: "/settings", element: <SettingsPage /> },
  { path: "*", element: <Landing /> },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
