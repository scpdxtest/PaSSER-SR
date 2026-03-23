import './App.css';
import "primereact/resources/themes/lara-light-teal/theme.css";
import "primereact/resources/primereact.min.css";
import "primeicons/primeicons.css";
import { Routes, Route } from 'react-router-dom';
import Navigation from './component/Nav';
import About from './component/About';
import ErrorBoundary from './component/ErrorBoundry';
import SelectModel from './component/SelectModel';
import TestWharf from './component/TestWharf';
import Screening from './component/Screening';

function App() {
  return (
    <div className="App">
      <ErrorBoundary>
       <Navigation />
            <Routes>
              <Route path='/about' element={<About/>}/>
              <Route path="/selectmodel" element={<SelectModel/>} />
              <Route path="/testwharf" element={<TestWharf/>} />
              <Route path="/screening" element={<Screening/>} />
            </Routes>
        </ErrorBoundary>
    </div>
  );
}

export default App;
