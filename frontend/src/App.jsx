import { Container, Nav, Navbar } from 'react-bootstrap'
import { NavLink, Route, Routes } from 'react-router-dom'
import NetworkMap from './pages/NetworkMap.jsx'
import InventoryForecast from './pages/InventoryForecast.jsx'
import SimulationLab from './pages/SimulationLab.jsx'
import StrategyComparison from './pages/StrategyComparison.jsx'
import AlertsPage from './pages/AlertsPage.jsx'

function Placeholder({ title }) {
  return (
    <div className="text-center text-muted py-5">
      <h4>{title}</h4>
      <p>Coming in the next step.</p>
    </div>
  )
}

export default function App() {
  return (
    <>
      <Navbar bg="dark" variant="dark" expand="lg" className="mb-4">
        <Container fluid>
          <Navbar.Brand>Supply Chain Digital Twin</Navbar.Brand>
          <Navbar.Toggle />
          <Navbar.Collapse>
            <Nav className="me-auto">
              <Nav.Link as={NavLink} to="/" end>Network</Nav.Link>
              <Nav.Link as={NavLink} to="/inventory">Inventory &amp; Forecast</Nav.Link>
              <Nav.Link as={NavLink} to="/lab">Simulation Lab</Nav.Link>
              <Nav.Link as={NavLink} to="/compare">Strategy Comparison</Nav.Link>
              <Nav.Link as={NavLink} to="/alerts">Alerts</Nav.Link>
              <Nav.Link as={NavLink} to="/whatif">What-If</Nav.Link>
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <Container fluid className="px-4 pb-5">
        <Routes>
          <Route path="/" element={<NetworkMap />} />
          <Route path="/inventory" element={<InventoryForecast />} />
          <Route path="/lab" element={<SimulationLab />} />
          <Route path="/compare" element={<StrategyComparison />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/whatif" element={<Placeholder title="What-If Chat" />} />
        </Routes>
      </Container>
    </>
  )
}