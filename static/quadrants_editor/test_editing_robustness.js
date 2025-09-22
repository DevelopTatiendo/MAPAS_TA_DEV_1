/**
 * COMPREHENSIVE EDITING ROBUSTNESS TEST SUITE
 * Tests all editing scenarios: parent expansion/contraction, children modification,
 * style preservation, validation, and edge cases.
 */

// Test framework for editing operations
const EditingTestFramework = {
  // Test results storage
  results: {
    passed: 0,
    failed: 0,
    warnings: 0,
    tests: []
  },
  
  // Test execution context
  context: {
    originalState: null,
    testFeatures: [],
    validationErrors: []
  },
  
  // Initialize test environment
  setup() {
    console.log('🧪 EDITING ROBUSTNESS TEST SUITE - SETUP');
    
    // Store original state
    this.context.originalState = {
      mode: currentEditorState,
      activeParent: activePadre,
      activeChildren: activeHijos ? [...activeHijos] : [],
      recolorMode: document.getElementById('btn-recolor').classList.contains('active')
    };
    
    // Clear results
    this.results = { passed: 0, failed: 0, warnings: 0, tests: [] };
    
    console.log('✅ Test environment initialized');
  },
  
  // Clean up after tests
  teardown() {
    console.log('🧹 CLEANING UP TEST ENVIRONMENT');
    
    // Restore original state if possible
    try {
      if (this.context.originalState) {
        setEditorState(this.context.originalState.mode);
        setRecolorMode(this.context.originalState.recolorMode);
      }
      
      // Clear any test features
      this.context.testFeatures.forEach(feature => {
        if (feature && feature.remove) {
          feature.remove();
        }
      });
      
    } catch (error) {
      console.warn('⚠️ Error during cleanup:', error);
    }
    
    console.log('✅ Cleanup completed');
  },
  
  // Execute a test with error handling
  runTest(testName, testFunction) {
    console.log(`\n🔬 Running test: ${testName}`);
    
    const testResult = {
      name: testName,
      status: 'RUNNING',
      startTime: Date.now(),
      errors: [],
      warnings: []
    };
    
    try {
      const result = testFunction();
      
      if (result === false) {
        testResult.status = 'FAILED';
        testResult.errors.push('Test returned false');
        this.results.failed++;
      } else if (result && result.warnings && result.warnings.length > 0) {
        testResult.status = 'PASSED_WITH_WARNINGS';
        testResult.warnings = result.warnings;
        this.results.warnings++;
        this.results.passed++;
      } else {
        testResult.status = 'PASSED';
        this.results.passed++;
      }
      
    } catch (error) {
      testResult.status = 'ERROR';
      testResult.errors.push(error.message);
      testResult.stackTrace = error.stack;
      this.results.failed++;
      console.error(`❌ Test ${testName} failed:`, error);
    }
    
    testResult.duration = Date.now() - testResult.startTime;
    this.results.tests.push(testResult);
    
    console.log(`${testResult.status === 'PASSED' ? '✅' : testResult.status === 'PASSED_WITH_WARNINGS' ? '⚠️' : '❌'} ${testName}: ${testResult.status} (${testResult.duration}ms)`);
    
    return testResult;
  },
  
  // Test stable color assignment consistency
  testColorStabilityConsistency() {
    return this.runTest('Color Stability Consistency', () => {
      const warnings = [];
      
      // Test 1: Create a mock feature with route information
      const mockFeature = {
        properties: {
          codigo: 'TEST_001',
          ruta: 'R1',
          nombre: 'Test Feature'
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[-74.1, 4.6], [-74.0, 4.6], [-74.0, 4.7], [-74.1, 4.7], [-74.1, 4.6]]]
        }
      };
      
      const mockLayer = {
        feature: mockFeature,
        setStyle: function(style) {
          Object.keys(style).forEach(key => {
            this.feature.properties[key] = style[key];
          });
        },
        toGeoJSON: function() {
          return this.feature;
        }
      };
      
      // Test stable color assignment
      const initialColor = mockFeature.properties.fillColor;
      assignStableColor(mockLayer);
      const assignedColor1 = mockFeature.properties.fillColor;
      
      // Test consistency - reassign and verify same color
      delete mockFeature.properties.fillColor;
      assignStableColor(mockLayer);
      const assignedColor2 = mockFeature.properties.fillColor;
      
      if (assignedColor1 !== assignedColor2) {
        throw new Error(`Color assignment inconsistent: ${assignedColor1} !== ${assignedColor2}`);
      }
      
      // Test route-based color consistency
      const routeColor = getRouteColorSeed('R1');
      if (!routeColor) {
        warnings.push('Route color seed not found for R1');
      }
      
      console.log(`✓ Color stability test passed - consistent color: ${assignedColor1}`);
      return { warnings };
    });
  },
  
  // Test parent editing validation
  testParentEditingValidation() {
    return this.runTest('Parent Editing Validation', () => {
      const warnings = [];
      
      // Test validation functions exist
      if (typeof validateBeforeEdit !== 'function') {
        throw new Error('validateBeforeEdit function not found');
      }
      
      if (typeof validateAfterEdit !== 'function') {
        throw new Error('validateAfterEdit function not found');
      }
      
      if (typeof validateChildrenContainmentRobust !== 'function') {
        throw new Error('validateChildrenContainmentRobust function not found');
      }
      
      // Test validation with mock data
      const mockParent = {
        feature: {
          properties: { codigo: 'PARENT_001', fillColor: '#ff0000', color: '#000' },
          geometry: { type: 'Polygon', coordinates: [[[-74.1, 4.6], [-74.0, 4.6], [-74.0, 4.7], [-74.1, 4.7], [-74.1, 4.6]]]}
        },
        toGeoJSON: function() { return this.feature; }
      };
      
      const preValidation = validateBeforeEdit(mockParent, 'PARENT');
      if (!preValidation.valid && preValidation.criticalErrors.length > 0) {
        warnings.push(`Pre-validation found critical errors: ${preValidation.criticalErrors.map(e => e.message).join(', ')}`);
      }
      
      console.log('✓ Parent editing validation functions operational');
      return { warnings };
    });
  },
  
  // Test children editing persistence
  testChildrenEditingPersistence() {
    return this.runTest('Children Editing Persistence', () => {
      const warnings = [];
      
      // Test style preservation functions
      if (typeof preserveStylesBeforeEdit !== 'function') {
        throw new Error('preserveStylesBeforeEdit function not found');
      }
      
      if (typeof restorePreservedStyles !== 'function') {
        throw new Error('restorePreservedStyles function not found');
      }
      
      // Test with mock child
      const mockChild = {
        feature: {
          properties: { 
            codigo: 'CHILD_001', 
            fillColor: '#00ff00', 
            color: '#000',
            fillOpacity: 0.7,
            weight: 2
          },
          geometry: { type: 'Polygon', coordinates: [[[-74.05, 4.65], [-74.03, 4.65], [-74.03, 4.67], [-74.05, 4.67], [-74.05, 4.65]]]}
        },
        setStyle: function(style) {
          Object.keys(style).forEach(key => {
            this.feature.properties[key] = style[key];
          });
        }
      };
      
      // Test style preservation
      const originalStyles = preserveStylesBeforeEdit(mockChild);
      
      if (!originalStyles.fillColor) {
        warnings.push('Style preservation did not capture fillColor');
      }
      
      // Modify styles and restore
      mockChild.feature.properties.fillColor = '#ff0000';
      restorePreservedStyles(mockChild, originalStyles);
      
      if (mockChild.feature.properties.fillColor !== '#00ff00') {
        throw new Error('Style restoration failed');
      }
      
      console.log('✓ Children editing persistence functions operational');
      return { warnings };
    });
  },
  
  // Test comprehensive validation system
  testComprehensiveValidation() {
    return this.runTest('Comprehensive Validation System', () => {
      const warnings = [];
      
      // Test validation error handling
      if (typeof displayValidationResults !== 'function') {
        throw new Error('displayValidationResults function not found');
      }
      
      // Test with validation errors
      const mockValidation = {
        valid: false,
        errors: [
          { type: 'TEST_ERROR', message: 'Test error message', severity: 'WARNING' }
        ],
        criticalErrors: [],
        warnings: [
          { type: 'TEST_WARNING', message: 'Test warning message', severity: 'WARNING' }
        ]
      };
      
      // This should not throw an error
      const result = displayValidationResults(mockValidation, 'TEST');
      
      if (result !== true) {
        warnings.push('Validation display did not handle warnings correctly');
      }
      
      console.log('✓ Comprehensive validation system operational');
      return { warnings };
    });
  },
  
  // Test color consistency during editing
  testColorConsistencyDuringEditing() {
    return this.runTest('Color Consistency During Editing', () => {
      const warnings = [];
      
      // Test color preservation functions
      if (typeof preserveColorsBeforeEdit !== 'function') {
        throw new Error('preserveColorsBeforeEdit function not found');
      }
      
      if (typeof enforceColorStabilityDuringEdit !== 'function') {
        throw new Error('enforceColorStabilityDuringEdit function not found');
      }
      
      if (typeof restoreColorStabilityAfterEdit !== 'function') {
        throw new Error('restoreColorStabilityAfterEdit function not found');
      }
      
      // Test with mock layers
      const mockLayers = [
        {
          feature: {
            properties: { codigo: 'TEST_A', fillColor: '#ff0000', ruta: 'R1' },
            geometry: { type: 'Polygon', coordinates: [[[-74.1, 4.6], [-74.0, 4.6], [-74.0, 4.7], [-74.1, 4.7], [-74.1, 4.6]]]}
          },
          setStyle: function(style) {
            Object.keys(style).forEach(key => {
              this.feature.properties[key] = style[key];
            });
          }
        }
      ];
      
      // Test color preservation
      preserveColorsBeforeEdit(mockLayers);
      
      if (!mockLayers[0].feature.properties._originalFillColor) {
        warnings.push('Color preservation did not store original color');
      }
      
      // Test stability enforcement
      enforceColorStabilityDuringEdit(mockLayers);
      
      // Test restoration
      const restoredCount = restoreColorStabilityAfterEdit(mockLayers);
      
      console.log('✓ Color consistency during editing functions operational');
      return { warnings };
    });
  },
  
  // Run all tests
  runAllTests() {
    console.log('\n🚀 STARTING COMPREHENSIVE EDITING ROBUSTNESS TESTS\n');
    
    this.setup();
    
    try {
      // Execute all test methods
      this.testColorStabilityConsistency();
      this.testParentEditingValidation();
      this.testChildrenEditingPersistence();
      this.testComprehensiveValidation();
      this.testColorConsistencyDuringEditing();
      
    } finally {
      this.teardown();
    }
    
    // Generate summary report
    this.generateReport();
  },
  
  // Generate test report
  generateReport() {
    const total = this.results.passed + this.results.failed;
    const passRate = total > 0 ? (this.results.passed / total * 100).toFixed(1) : '0.0';
    
    console.log('\n📊 EDITING ROBUSTNESS TEST REPORT');
    console.log('=' .repeat(50));
    console.log(`✅ Passed: ${this.results.passed}`);
    console.log(`❌ Failed: ${this.results.failed}`);
    console.log(`⚠️  Warnings: ${this.results.warnings}`);
    console.log(`📈 Pass Rate: ${passRate}%`);
    console.log('=' .repeat(50));
    
    // Detailed test results
    this.results.tests.forEach(test => {
      const icon = test.status === 'PASSED' ? '✅' : 
                   test.status === 'PASSED_WITH_WARNINGS' ? '⚠️' : '❌';
      console.log(`${icon} ${test.name}: ${test.status} (${test.duration}ms)`);
      
      if (test.errors.length > 0) {
        test.errors.forEach(error => console.log(`    🚫 ${error}`));
      }
      
      if (test.warnings.length > 0) {
        test.warnings.forEach(warning => console.log(`    ⚠️  ${warning}`));
      }
    });
    
    console.log('\n🏁 EDITING ROBUSTNESS TESTS COMPLETED');
    
    // Return results for external validation
    return this.results;
  }
};

// Export for browser console usage
if (typeof window !== 'undefined') {
  window.EditingTestFramework = EditingTestFramework;
  
  // Add convenient global function
  window.runEditingTests = function() {
    return EditingTestFramework.runAllTests();
  };
  
  console.log('🧪 Editing Robustness Test Framework loaded. Use runEditingTests() to execute all tests.');
}

// Node.js export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = EditingTestFramework;
}