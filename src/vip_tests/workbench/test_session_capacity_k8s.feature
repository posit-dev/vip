@workbench
Feature: Kubernetes session capacity and autoscaling
  As a Posit Team administrator running Workbench on Kubernetes
  I want to verify that the deployment handles autoscaling, capacity limits,
  and resource profile enforcement correctly
  So that I can validate Kubernetes-specific session behavior

  Scenario: Autoscaler adds a node when sessions fill current capacity
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    When I record the current node count
    And I launch sessions until the current node capacity is full
    Then the autoscaler adds at least one new node

  Scenario: New session lands on a node after scale-up
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    When I launch sessions in quick succession to trigger autoscaling
    Then all launched sessions reach Active state
    And I clean up all launched sessions

  Scenario: Session count respects the configured maximum
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    And a maximum session count is configured
    When I launch sessions up to the configured maximum
    Then all launched sessions reach Active state
    And I clean up all launched sessions

  Scenario: Sessions launched in quick succession all reach Active state
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    When I launch multiple sessions concurrently
    Then all launched sessions reach Active state
    And I clean up all launched sessions

  Scenario: Session is routed to the expected node pool for the resource profile
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    And node-pool-to-profile mappings are configured
    When I launch a session with a profiled resource profile
    Then the session pod runs on a node in the expected node pool
    And I clean up all launched sessions

  Scenario: Resource profile enforces CPU and memory limits
    Given Workbench is accessible and I am logged in
    And the Kubernetes cluster is configured
    And resource limit expectations are configured
    When I launch a session with a resource-limited profile
    Then the session pod has the expected CPU and memory limits
    And I clean up all launched sessions
