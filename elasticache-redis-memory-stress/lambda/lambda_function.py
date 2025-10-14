import json
import redis
import boto3
import logging
import time
import random
import string

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info(f"Lambda invoked with action: {event.get('action', 'unknown')}")
    logger.info(f"Event: {json.dumps(event, default=str)}")
    
    action = event['action']
    
    if action == 'apply_stress':
        return apply_stress(event)
    elif action == 'test_evictions':
        return test_evictions(event)
    elif action == 'cleanup':
        return cleanup(event)
    else:
        logger.warning(f"Unknown action: {action}")
        return None

def apply_stress(event):
    target_clusters = event['targetClusters']
    fill_percentage = int(event['memoryFillPercentage'])
    duration_minutes = event.get('durationMinutes', 0)
    
    logger.info(f"Applying stress to {len(target_clusters)} clusters with {fill_percentage}% memory fill for {duration_minutes} minutes")
    
    results = []
    stress_keys = []
    
    for cluster_info in target_clusters:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        logger.info(f"Connecting to cluster {cluster_id} at {endpoint}:{port}")
        
        try:
            r = redis.Redis(host=endpoint, port=port, decode_responses=True)
            logger.info(f"Setting LRU eviction policy for cluster {cluster_id}")
            r.config_set('maxmemory-policy', 'allkeys-lru')
            
            memory_info = r.info('memory')
            max_memory = memory_info.get('maxmemory', 0)
            used_memory = memory_info.get('used_memory', 0)
            
            logger.info(f"Cluster {cluster_id} memory: used={used_memory}, max={max_memory}")
            
            if max_memory == 0:
                max_memory = used_memory + (100 * 1024 * 1024)
                logger.info(f"No max memory set, using calculated max: {max_memory}")
                r.config_set('maxmemory', max_memory)
            
            target_memory = max_memory * (fill_percentage / 100.0)
            key_size = 50000
            cluster_keys = []
            key_count = 0
            
            logger.info(f"Target memory for cluster {cluster_id}: {target_memory} bytes")
            
            while True:
                current_memory = r.info('memory')['used_memory']
                if current_memory >= target_memory:
                    logger.info(f"Target memory reached for cluster {cluster_id}: {current_memory} >= {target_memory}")
                    break
                    
                key = f"fis_stress:{cluster_id}:{key_count}"
                value = 'X' * key_size
                
                r.set(key, value)
                cluster_keys.append(key)
                key_count += 1
                
                if key_count % 50 == 0:
                    stats = r.info('stats')
                    evicted = stats.get('evicted_keys', 0)
                    logger.info(f"Cluster {cluster_id}: {key_count} keys created, {current_memory} bytes used, {evicted} evicted")
                    if evicted > 0:
                        results.append(f"Cluster {cluster_id}: Evictions started at {key_count} keys")
                
                if key_count >= 5000:
                    break
            
            final_memory = r.info('memory')['used_memory']
            final_stats = r.info('stats')
            evicted_keys = final_stats.get('evicted_keys', 0)
            
            stress_keys.append({
                'cluster_id': cluster_id,
                'endpoint': endpoint,
                'port': port,
                'keys': cluster_keys
            })
            
            results.append(f"Cluster {cluster_id}: Created {key_count} keys, memory: {final_memory}, evicted: {evicted_keys}")
            
        except Exception as e:
            logger.error(f"Failed to apply stress to cluster {cluster_id}: {str(e)}")
            results.append(f"Failed to apply stress to cluster {cluster_id}: {str(e)}")
    
    # Maintain stress for specified duration
    if duration_minutes > 0:
        logger.info(f"Maintaining stress for {duration_minutes} minutes")
        time.sleep(duration_minutes * 60)
        logger.info("Duration complete")
    
    logger.info(f"Stress application complete. Results: {results}")
    return {
        'stressKeys': stress_keys,
        'results': results
    }

def test_evictions(event):
    stress_keys = event['stressKeys']
    logger.info(f"Testing evictions on {len(stress_keys)} clusters")
    results = []
    
    for cluster_info in stress_keys:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        logger.info(f"Testing evictions for cluster {cluster_id}")
        
        try:
            r = redis.Redis(host=endpoint, port=port, decode_responses=True)
            
            logger.info(f"Adding 100 test keys to trigger evictions in cluster {cluster_id}")
            for i in range(100):
                r.set(f"eviction_test:{cluster_id}:{i}", "Y" * 30000)
            
            stats = r.info('stats')
            memory_info = r.info('memory')
            
            results.append({
                'cluster_id': cluster_id,
                'total_evicted_keys': stats.get('evicted_keys', 0),
                'current_memory_mb': round(memory_info['used_memory'] / (1024*1024), 2),
                'max_memory_mb': round(memory_info.get('maxmemory', 0) / (1024*1024), 2),
                'eviction_policy': r.config_get('maxmemory-policy')['maxmemory-policy']
            })
            
        except Exception as e:
            logger.error(f"Failed to test evictions for cluster {cluster_id}: {str(e)}")
            results.append({
                'cluster_id': cluster_id,
                'error': str(e)
            })
    
    logger.info(f"Eviction testing complete: {len(results)} results")
    return results

def cleanup(event):
    stress_keys = event['stressKeys']
    logger.info(f"Cleaning up stress keys from {len(stress_keys)} clusters")
    results = []
    
    for cluster_info in stress_keys:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        keys = cluster_info['keys']
        
        logger.info(f"Cleaning up {len(keys)} keys from cluster {cluster_id}")
        
        try:
            r = redis.Redis(host=endpoint, port=port, decode_responses=True)
            
            deleted_count = 0
            if keys:
                deleted_count += r.delete(*keys)
            
            eviction_keys = r.keys(f"eviction_test:{cluster_id}:*")
            if eviction_keys:
                deleted_count += r.delete(*eviction_keys)
            
            results.append(f"Cluster {cluster_id}: Deleted {deleted_count} total keys")
                
        except Exception as e:
            results.append(f"Failed to cleanup cluster {cluster_id}: {str(e)}")
    
    return results
