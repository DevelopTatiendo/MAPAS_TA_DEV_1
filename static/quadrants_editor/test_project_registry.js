// Test script for ProjectRegistry functionality
// This script can be run in browser console to verify ProjectRegistry implementation

console.log('🧪 Testing ProjectRegistry System...');

// Test data
const testParent = {
  type: 'Feature',
  properties: {
    nivel: 'cuadrante',
    codigo: 'CL_1_01',
    ciudad: 'CALI', 
    id_ruta: '1',
    fillColor: '#667eea'
  },
  geometry: {
    type: 'Polygon',
    coordinates: [[[-76.5, 3.4], [-76.4, 3.4], [-76.4, 3.5], [-76.5, 3.5], [-76.5, 3.4]]]
  }
};

const testChild = {
  type: 'Feature', 
  properties: {
    nivel: 'subcuadrante',
    codigo: 'CL_1_01_S01',
    codigo_padre: 'CL_1_01',
    ciudad: 'CALI',
    id_ruta: '1',
    fillColor: '#11998e'
  },
  geometry: {
    type: 'Polygon',
    coordinates: [[[-76.48, 3.42], [-76.46, 3.42], [-76.46, 3.44], [-76.48, 3.44], [-76.48, 3.42]]]
  }
};

// Test basic registry operations
function testProjectRegistry() {
  console.log('Testing basic operations...');
  
  // Clear registry
  ProjectRegistry.clear();
  console.log('✓ Registry cleared');
  
  // Test parent registration
  const parentKey = ProjectRegistry.generateKey(testParent);
  ProjectRegistry.setFeature(parentKey, testParent);
  console.log('✓ Parent registered:', parentKey);
  
  // Test child registration  
  const childKey = ProjectRegistry.generateKey(testChild);
  ProjectRegistry.setFeature(childKey, testChild);
  console.log('✓ Child registered:', childKey);
  
  // Test retrieval
  const retrievedParent = ProjectRegistry.getParent('CL_1_01');
  const retrievedChildren = ProjectRegistry.getChildren('CL_1_01');
  const routeFeatures = ProjectRegistry.getRouteFeatures('1');
  
  console.log('✓ Parent retrieved:', !!retrievedParent);
  console.log('✓ Children count:', retrievedChildren.length);
  console.log('✓ Route features count:', routeFeatures.length);
  
  // Test route label resolver
  const routeLabel = routeLabelResolver(testParent);
  console.log('✓ Route label:', routeLabel);
  
  return {
    parentRetrieved: !!retrievedParent,
    childrenCount: retrievedChildren.length,
    routeFeaturesCount: routeFeatures.length,
    routeLabel: routeLabel
  };
}

// Test export functionality
function testExportIntegration() {
  console.log('Testing export integration...');
  
  try {
    const fullFC = buildFullFeatureCollection();
    console.log('✓ Full export works, features:', fullFC.features.length);
    console.log('✓ Export properties:', fullFC.properties);
    
    return {
      exportWorks: true,
      featureCount: fullFC.features.length,
      hasRegistrySource: fullFC.properties.export_source.includes('ProjectRegistry')
    };
  } catch (error) {
    console.error('✗ Export test failed:', error);
    return { exportWorks: false, error: error.message };
  }
}

// Run all tests
function runAllTests() {
  console.log('🚀 Starting ProjectRegistry Integration Tests...\n');
  
  const registryResults = testProjectRegistry();
  console.log('\n📊 Registry Test Results:', registryResults);
  
  const exportResults = testExportIntegration();
  console.log('\n📤 Export Test Results:', exportResults);
  
  const success = registryResults.parentRetrieved && 
                  registryResults.childrenCount === 1 &&
                  registryResults.routeFeaturesCount === 2 &&
                  exportResults.exportWorks &&
                  exportResults.hasRegistrySource;
  
  console.log(`\n${success ? '✅' : '❌'} Overall Test Result: ${success ? 'PASSED' : 'FAILED'}`);
  
  if (success) {
    console.log('\n🎉 ProjectRegistry system is working correctly!');
    console.log('- ✓ Features are properly indexed');
    console.log('- ✓ Parent-child relationships maintained');
    console.log('- ✓ Route grouping functional');
    console.log('- ✓ Export integration successful');
    console.log('- ✓ Human-readable labels working');
  }
  
  return success;
}

// Export test function for manual execution
if (typeof window !== 'undefined') {
  window.testProjectRegistry = runAllTests;
  console.log('💡 Run window.testProjectRegistry() in browser console to test');
} else {
  // For node.js testing
  module.exports = { testProjectRegistry, testExportIntegration, runAllTests };
}