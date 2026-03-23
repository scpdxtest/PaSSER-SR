import { Menubar } from 'primereact/menubar';
import "primereact/resources/primereact.min.css";
import "primeicons/primeicons.css";
import { useState, useEffect } from 'react';
import { blueFontSmall } from './mylib';     
import {checkBCEndpoint, checkIPFSEndpoint} from './BCEndpoints.js';
import aboutIcon from './about.png';
import './Nav.css';
import testingIcon from './testing_icon-icons.com_72182.png'

const Navigation = () => {
    const [selectedModel, setSelectedModel] = useState(localStorage.getItem("selectedLLMModel") || 'Default -> mixtral');
    const [selectedOllama, setSelectedOllama] = useState(localStorage.getItem("selectedOllama") || 'http://');
    const [ChromaDBPath, setChromaDBPath] = useState(localStorage.getItem("selectedChromaDB") || 'http://');
    const [multiAgentAPI, setMultiAgentAPI] = useState(localStorage.getItem("selectedMultiAgent") || 'http://');

    useEffect(() => {
        checkBCEndpoint().then(async (res) => {
            localStorage.setItem("bcEndpoint", res);
        });
        checkIPFSEndpoint().then(async (res) => {
            localStorage.setItem("ipfsEndpoint_host", res.host);
            localStorage.setItem("ipfsEndpoint_port", res.port);
        });
    }, []);

    const navlist = [
      { label: 'About', icon: <img src={aboutIcon} alt="About" width="22" height="22" />, command: () => {
          window.location.href = './#/about';
        }
      },
      {
        label: 'Tests',
        icon: <img src={testingIcon} alt="Tests" width="20" height="20" />,
        items: [
          { label: 'Screening Test', icon: <span style={{ color: 'green' }} className="pi pi-fw pi-filter"></span>, command: () => { window.location.href = './#/screening'; } }
        ]
      },
      {
        label: 'Configuration',
        icon: <span style={{ color: 'blue' }} className="pi pi-fw pi-cog"></span>,
        items: [
          { label: 'Settings', icon: <span style={{ color: 'blue' }} className="pi pi-fw pi-cog"></span>, command: () => { window.location.href = './#/selectmodel'; } }
        ]
      },
      { label: 'AnchorLogin', icon: <span style={{ color: 'orange' }} className="pi pi-fw pi-key"></span>, command: () => { window.location.href = './#/testwharf'; } }
    ];
    
    return(

        <header>
            <nav>
                <ul>
                    <Menubar 
                        model={navlist} 
                        end={
                            <div>
                                <div style={blueFontSmall}><b>OllamaAPI:</b>{selectedOllama} | <b>Model:</b>{selectedModel}</div>
                                <div style={blueFontSmall}><b>ChromaAPI:</b>{ChromaDBPath} | <b>BCName:</b>{localStorage.getItem('wharf_user_name')}</div>
                                <div style={blueFontSmall}><b>MultiAgentAPI:</b>{multiAgentAPI}</div>
                            </div>
                        }
                    />
                </ul>
            </nav>
         </header>


    )

}

export default Navigation;