const { execSync } = require('child_process');
const packageJson = require('../package.json');

const version = packageJson.version;
const tagName = `v${version}`;
const description = `Build version ${version} - ${new Date().toLocaleString()}`;

try {
    // Check if the tag already exists
    const existingTags = execSync('git tag', { encoding: 'utf-8' }).split('\n');
    if (existingTags.includes(tagName)) {
        console.log(`⚠️ Tag ${tagName} already exists. Skipping tag creation.`);
    } else {
        // Create a Git tag with the version and description
        execSync(`git tag -a ${tagName} -m "${description}"`, { stdio: 'inherit' });

        // Push the tag to the remote repository
        execSync('git push origin --tags', { stdio: 'inherit' });

        console.log(`✅ Successfully tagged version ${tagName} with description: "${description}"`);
    }
} catch (error) {
    console.error('❌ Failed to tag version:', error.message);
    process.exit(1);
}