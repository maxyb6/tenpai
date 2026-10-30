import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import MiniAppRoute from "./mini/MiniApp";
import Account from "./pages/Account";
import Approvals from "./pages/Approvals";
import Portfolio from "./pages/Portfolio";
import Today from "./pages/Today";
import Payments from "./pages/Payments";
import Results from "./pages/Results";
import Compliance from "./pages/Compliance";
import Settings from "./pages/Settings";
import { FieldManager, OfficerView } from "./pages/Field";
import { AppProvider, useApp } from "./state";

function Home() {
  const { role } = useApp();
  const to = { leadership: "/results", head_of_collections: "/portfolio", credit_officer: "/field" }[role] ?? "/today";
  return <Navigate to={to} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route path="/m/:token" element={<MiniAppRoute />} />
          {/* Officer phone view: full screen, no console chrome. */}
          <Route path="/field" element={<OfficerView />} />
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/today" element={<Today />} />
            <Route path="/cases/:id" element={<Account />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/field-manager" element={<FieldManager />} />
            <Route path="/payments" element={<Payments />} />
            <Route path="/results" element={<Results />} />
            <Route path="/compliance" element={<Compliance />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
