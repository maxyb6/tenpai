import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Card, PageHeader } from "./components/ui";
import MiniAppRoute from "./mini/MiniApp";
import Account from "./pages/Account";
import Approvals from "./pages/Approvals";
import Portfolio from "./pages/Portfolio";
import Today from "./pages/Today";
import { AppProvider, useApp } from "./state";

function Later({ question, stage }: { question: string; stage: string }) {
  return (
    <>
      <PageHeader question={question} />
      <Card><div className="text-slate/60">Coming in build {stage}.</div></Card>
    </>
  );
}

function Home() {
  const { role } = useApp();
  return <Navigate to={role === "leadership" ? "/portfolio" : role === "head_of_collections" ? "/portfolio" : "/today"} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route path="/m/:token" element={<MiniAppRoute />} />
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/today" element={<Today />} />
            <Route path="/cases/:id" element={<Account />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/field-manager" element={<Later question="Where should my officers go?" stage="stage 7" />} />
            <Route path="/field" element={<Later question="Today's visits" stage="stage 7" />} />
            <Route path="/payments" element={<Later question="Has the money arrived, and is it posted?" stage="stage 6" />} />
            <Route path="/results" element={<Later question="Is this working?" stage="stage 8" />} />
            <Route path="/compliance" element={<Later question="Can we prove we treat borrowers fairly?" stage="stage 8" />} />
            <Route path="/settings" element={<Later question="What are our rules?" stage="stage 8" />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
