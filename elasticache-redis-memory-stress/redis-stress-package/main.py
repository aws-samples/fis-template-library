import subprocess
import time
import boto3
from utils.redis_operations import RedisStressOperations

def get_target_clusters(events, context):
    """Find ElastiCache Redis clusters with specified tags"""
    region = events['region']
    tag_key = events['tagKey']
    tag_value = events['tagValue']
    
    elasticache = boto3.client('elasticache', region_name=region)
    target_clusters = []
    
    paginator = elasticache.get_paginator('describe_cache_clusters')
    
    for page in paginator.paginate():
        for cluster in page['CacheClusters']:
            if cluster['Engine'] == 'redis' and cluster['CacheClusterStatus'] == 'available':
                cluster_id = cluster['CacheClusterId']
                
                try:
                    tags_response = elasticache.list_tags_for_resource(
                        ResourceName=f"arn:aws:elasticache:{region}:{boto3.client('sts').get_caller_identity()['Account']}:cluster:{cluster_id}"
                    )
                    
                    tags = {tag['Key']: tag['Value'] for tag in tags_response.get('TagList', [])}
                    
                    if tags.get(tag_key) == tag_value:
                        target_clusters.append({
                            'cluster_id': cluster_id,
                            'endpoint': cluster['RedisConfiguration']['PrimaryEndpoint']['Address'] if 'RedisConfiguration' in cluster else cluster['CacheNodes'][0]['Endpoint']['Address'],
                            'port': cluster['RedisConfiguration']['PrimaryEndpoint']['Port'] if 'RedisConfiguration' in cluster else cluster['CacheNodes'][0]['Endpoint']['Port']
                        })
                                
                except Exception as e:
                    print(f"Error processing cluster {cluster_id}: {str(e)}")
                    continue
                    
    return target_clusters

def apply_memory_stress(events, context):
    """Apply memory stress using redis-cli commands from experiments.md"""
    target_clusters = events['targetClusters']
    duration_minutes = events.get('durationMinutes', 15)
    
    redis_ops = RedisStressOperations()
    results = []
    
    for cluster_info in target_clusters:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        print(f"Applying memory stress to cluster {cluster_id}")
        
        try:
            # Apply stress using experiments.md commands
            redis_ops.setup_memory_policy(endpoint, port)
            redis_ops.fill_cache_with_keys(endpoint, port, cluster_id)
            redis_ops.apply_benchmark_pressure(endpoint, port)
            
            # Maintain for duration
            if duration_minutes > 0:
                print(f"Maintaining stress for {duration_minutes} minutes")
                time.sleep(duration_minutes * 60)
            
            results.append(f"Successfully applied stress to {cluster_id}")
            
        except Exception as e:
            results.append(f"Failed to stress {cluster_id}: {str(e)}")
    
    return {'results': results}

def cleanup_memory_stress(events, context):
    """Clean up test data from Redis clusters"""
    target_clusters = events['targetClusters']
    redis_ops = RedisStressOperations()
    results = []
    
    for cluster_info in target_clusters:
        cluster_id = cluster_info['cluster_id']
        endpoint = cluster_info['endpoint']
        port = cluster_info['port']
        
        try:
            redis_ops.cleanup_cluster(endpoint, port)
            results.append(f"Cleaned up {cluster_id}")
        except Exception as e:
            results.append(f"Failed to cleanup {cluster_id}: {str(e)}")
    
    return {'results': results}
