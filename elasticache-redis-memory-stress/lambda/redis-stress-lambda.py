import json
import redis
import boto3

def lambda_handler(event, context):
    action = event['action']
    
    if action == 'apply_stress':
        return apply_stress(event)
    elif action == 'test_evictions':
        return test_evictions(event)
    elif action == 'cleanup':
        return cleanup(event)

def apply_stress(event):
    target_clusters = event['targetClusters']
    fill_percentage = int(event['memoryFillPercentage'])
    
    results = []
    stress_keys = []
    
    for cluster_info in target_clusters:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        try:
            r = redis.Redis(host=endpoint, port=port, decode_responses=True)
            r.config_set('maxmemory-policy', 'allkeys-lru')
            
            memory_info = r.info('memory')
            max_memory = memory_info.get('maxmemory', 0)
            used_memory = memory_info.get('used_memory', 0)
            
            if max_memory == 0:
                max_memory = used_memory + (100 * 1024 * 1024)
                r.config_set('maxmemory', max_memory)
            
            target_memory = max_memory * (fill_percentage / 100.0)
            key_size = 50000
            cluster_keys = []
            key_count = 0
            
            while True:
                current_memory = r.info('memory')['used_memory']
                if current_memory >= target_memory:
                    break
                    
                key = f"fis_stress:{cluster_id}:{key_count}"
                value = 'X' * key_size
                
                r.set(key, value)
                cluster_keys.append(key)
                key_count += 1
                
                if key_count % 50 == 0:
                    stats = r.info('stats')
                    evicted = stats.get('evicted_keys', 0)
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
            results.append(f"Failed to apply stress to cluster {cluster_id}: {str(e)}")
    
    return {
        'stressKeys': stress_keys,
        'results': results
    }

def test_evictions(event):
    stress_keys = event['stressKeys']
    results = []
    
    for cluster_info in stress_keys:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        try:
            r = redis.Redis(host=endpoint, port=port, decode_responses=True)
            
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
            results.append({
                'cluster_id': cluster_id,
                'error': str(e)
            })
    
    return results

def cleanup(event):
    stress_keys = event['stressKeys']
    results = []
    
    for cluster_info in stress_keys:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        keys = cluster_info['keys']
        
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
