import React, { useEffect, useState } from "react";
import backgroundImage from './PasserLogo4_GPT.png';
import packageJson from '../../package.json';

const About = () => {
    const [version, setVersion] = useState('');
    const hello = 'Welcome to PaSSER: Platform for Retrieval-Augmented Generation';
    const aboutContent = [
        'PaSSER is a web application designed for implementing and testing Retrieval-Augmented Generation (RAG) models. It offers a user-friendly interface for adaptive testing across various scenarios, integrating large language models (LLMs) like Mistral:7b, Llama2:7b, and Orca2:7b.',
        'PaSSER provides a comprehensive set of standard Natural Language Processing (NLP) metrics, facilitating thorough evaluation of model performance.',
        'The platform fosters collaboration and transparency within the research community, empowering users to contribute to the advancement of language model research and development.',
        'This work was supported by the Bulgarian Ministry of Education and Science under the National Research Program “Smart crop production” approved by the Ministry Council No. 866/26.11.2020.'
    ];

    useEffect(() => {
        setVersion(packageJson.version);
    }, []);

    return (
        <div style={{ display: 'flex', height: '100vh', width: '100%', fontFamily: 'Arial, sans-serif' }}>
            {/* Left Section with Background Image */}
            <div
                style={{
                    flex: '50%',
                    backgroundImage: `url(${backgroundImage})`,
                    backgroundSize: 'cover',
                    backgroundPosition: 'center center',
                    filter: 'brightness(0.9)',
                }}
            ></div>

            {/* Right Section with Content */}
            <div style={{ flex: '50%', backgroundColor: '#f9f9f9', color: '#333', padding: '40px', overflowY: 'auto' }}>
                <div style={{ marginBottom: '20px' }}>
                    <h1 style={{ fontSize: '2.5em', color: '#333', marginBottom: '10px' }}>{hello}</h1>
                    <p style={{ fontSize: '1em', color: '#888' }}>Version: <strong>{version}</strong></p>
                </div>

                {aboutContent.map((text, index) => (
                    <div key={index} style={{ marginBottom: '20px' }}>
                        <h2 style={{ fontSize: '1.2em', fontWeight: 'normal', color: '#555', lineHeight: '1.6' }}>
                            {text}
                        </h2>
                    </div>
                ))}

            </div>
        </div>
    );
};

export default About;