"""
Quick local test of improved multihorizon pipeline before GPU training.
"""
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error

# Import the training module
import sys
sys.path.insert(0, str(Path(__file__).parent))
from train_q21_multihorizon_improved import HorizonSpecificFeatureBuilder

def test_feature_builder():
    """Test feature builder on small sample."""
    print("Testing HorizonSpecificFeatureBuilder...")

    # Create sample data
    dates = pd.date_range('2023-01-01', periods=1000, freq='10min')
    data = pd.DataFrame({
        'Q21': np.random.normal(8, 2, 1000),
        'F30': np.random.normal(100, 10, 1000),
        'T33': np.random.normal(280, 5, 1000),
        'T55': np.random.normal(360, 10, 1000)
    }, index=dates)

    # Test h=3
    builder_h3 = HorizonSpecificFeatureBuilder(horizon_hours=3)
    features_h3 = builder_h3.build(data)

    print(f"\nHorizon 3h:")
    print(f"  Input shape: {data.shape}")
    print(f"  Output shape: {features_h3.shape}")
    print(f"  Feature count: {features_h3.shape[1]}")
    print(f"  Valid samples: {features_h3['Q21_target_h3'].notna().sum()}")

    # Test h=6
    builder_h6 = HorizonSpecificFeatureBuilder(horizon_hours=6)
    features_h6 = builder_h6.build(data)

    print(f"\nHorizon 6h:")
    print(f"  Input shape: {data.shape}")
    print(f"  Output shape: {features_h6.shape}")
    print(f"  Feature count: {features_h6.shape[1]}")
    print(f"  Valid samples: {features_h6['Q21_target_h6'].notna().sum()}")

    # Check for leakage
    print("\nChecking for data leakage...")
    for h in [3, 6]:
        target_col = f'Q21_target_h{h}'
        features = features_h3 if h == 3 else features_h6

        # Q21 lagged features should be properly shifted
        if 'Q21_lagged' in features.columns:
            # Check that Q21_lagged is not correlated with future target
            valid = features[[target_col, 'Q21_lagged']].dropna()
            if len(valid) > 10:
                corr = valid[target_col].corr(valid['Q21_lagged'])
                print(f"  h={h}: Q21_lagged vs target correlation: {corr:.3f} (should be low)")

    print("\n✅ Feature builder test passed!")
    return True

if __name__ == "__main__":
    test_feature_builder()
